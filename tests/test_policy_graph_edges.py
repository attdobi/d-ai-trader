"""Edge derivation / validation / edges.json on hand-built Node lists, plus decider_memory
(ltm) snapshot nodes. Independent of decompose.py."""
from __future__ import annotations

import json
from datetime import datetime

from policy_graph.code_blocks import BLOCKS_BY_ID, code_nodes
from policy_graph.edges import (
    derive_edges, jaccard, read_edges_json, resolve_link, tokens, validate_graph, write_edges_json,
)
from policy_graph.lessons import format_memory_line, ltm_group_node, ltm_nodes, snapshot_sha
from policy_graph.model import Edge, Node

STAMP = "DeciderAgent.cfg_test.v21"


def _n(id_, parent, *, node_type="section", field="strategy_directives", body="", owner="db", **kw):
    agent = {"DA": "DeciderAgent", "SA": "SummarizerAgent", "FA": "FeedbackAgent"}[id_.split(".")[0]]
    return Node(id=id_, agent=agent, title=id_.rsplit(".", 1)[-1], node_type=node_type, parent=parent,
                field=field, body=body, owner=owner, **kw)


def _keys(edges, edge_type=None):
    return {(e.source, e.target, e.edge_type) for e in edges if edge_type is None or e.edge_type == edge_type}


# ----------------------------------------------------------------------------- small hand-built graph
def _small_graph():
    return [
        _n("DA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.template.system", "DA.root", node_type="template", field="system_prompt",
           body="You are the decider.\n{strategy_directives}\n"),
        _n("DA.template.user", "DA.root", node_type="template", field="user_prompt_template", body="INPUTS {holdings}"),
        _n("DA.directives", "DA.root", node_type="field", body=""),
        _n("DA.directives.strategy", "DA.directives", body="## Current Strategy"),
        _n("DA.directives.strategy.regime_gate", "DA.directives.strategy", node_type="rule",
           body="1. REGIME GATE — read the index regime first; RISK-OFF means cash is the default.",
           tags=["regime"]),
        _n("DA.directives.strategy.priced_kill", "DA.directives.strategy", node_type="rule",
           body="3. PRICED KILL — every BUY ends with K:<price>;D:<%>. See [[reentry-quarantine]] and [[IRDM]].",
           tags=["priced-kill"], links=["priced_kill_lesson"]),
        _n("DA.soul", "DA.root", node_type="field", field="soul", body=""),
        _n("DA.soul.mission", "DA.soul", field="soul", body="## Mission\nFront-run, never chase."),
        _n("DA.memory", "DA.root", node_type="field", field="memory", body=""),
        _n("DA.memory.lessons", "DA.memory", field="memory", body="## Lessons Learned"),
        _n("DA.memory.lessons.priced_kill", "DA.memory.lessons", node_type="lesson", field="memory",
           body="- **#priced-kill** every BUY carries a priced kill; no widening.", tags=["priced-kill"]),
        _n("DA.memory.lessons.reentry_quarantine", "DA.memory.lessons", node_type="lesson", field="memory",
           body="- **#reentry-quarantine** no same-ticker re-entry within 3 days.", tags=["reentry-quarantine"]),
        _n("DA.memory.log.2026_06_29_irdm", "DA.memory", node_type="entry", field="memory",
           body="## 2026-06-29 #IRDM chased the gap", tags=["irdm"], tickers=["IRDM"]),
        _n("DA.runtime.inputs", "DA.root", node_type="data", field=None, owner="runtime", body="per-cycle blocks"),
        _n("DA.code", "DA.root", node_type="code", field=None, owner="generated", body=""),
        _n("DA.code.confirmation_policy", "DA.code", node_type="code", field=None, owner="code",
           body="CONFIRMATION POLICY … priced kill", order=0, extra={"position": "user_prompt_tail"}),
        _n("DA.code.quarantine_line", "DA.code", node_type="code", field=None, owner="code",
           body="# QUARANTINE (exited within the last 2 sessions)", order=1, extra={"position": "user_prompt_dynamic"}),
        _n("DA.ltm", "DA.root", node_type="ltm", field=None, owner="decider_memory", body=""),
        _n("DA.ltm.20", "DA.ltm", node_type="ltm", field=None, owner="decider_memory",
           body="- [rule] (IRDM) every BUY carries a priced kill; no widening.", tickers=["IRDM"],
           edges=[{"type": "enforced_by", "to": "DA.code.quarantine_line", "via": "test"},
                  {"type": "subtype_of", "to": "DA.root"}]),
    ]


def test_small_graph_exact_edges():
    nodes = _small_graph()
    edges = derive_edges(nodes, version_stamp=STAMP)
    by_id = {n.id: n for n in nodes}

    # hierarchy: one subtype_of per non-root node, none for the root
    expected_hier = {(n.id, n.parent, "subtype_of") for n in _small_graph() if n.parent}
    assert _keys(edges, "subtype_of") == expected_hier

    # assembly
    assert _keys(edges, "includes") == {
        ("DA.template.system", "DA.directives", "includes"),
        ("DA.template.system", "DA.soul", "includes"),
        ("DA.template.system", "DA.memory", "includes"),
        ("DA.template.user", "DA.code.confirmation_policy", "includes"),
        ("DA.template.user", "DA.code.quarantine_line", "includes"),
        ("DA.template.user", "DA.ltm", "includes"),
        ("DA.template.user", "DA.runtime.inputs", "includes"),
    }
    via = {(e.source, e.target): e.via for e in edges if e.edge_type == "includes"}
    assert via[("DA.template.system", "DA.directives")] == "{strategy_directives}"
    assert via[("DA.template.system", "DA.soul")] == "## AGENT IDENTITY"
    assert via[("DA.template.system", "DA.memory")] == "## LESSONS FROM EXPERIENCE"
    assert via[("DA.template.user", "DA.code.confirmation_policy")] == "user_prompt_tail"

    # wikilinks: [[reentry-quarantine]] → last-segment match ignoring -/_; links= entry → tag match
    assert (("DA.directives.strategy.priced_kill", "DA.memory.lessons.reentry_quarantine", "related_to")
            in _keys(edges, "related_to"))
    rel = {(e.source, e.target): e for e in edges if e.edge_type == "related_to"}
    assert rel[("DA.directives.strategy.priced_kill", "DA.memory.lessons.reentry_quarantine")].via == "[[reentry-quarantine]]"
    assert rel[("DA.directives.strategy.priced_kill", "DA.memory.lessons.reentry_quarantine")].provenance == "derived:wikilink"
    # shared #priced-kill tag (2 nodes) → related_to via "#priced-kill"
    assert rel[("DA.directives.strategy.priced_kill", "DA.memory.lessons.priced_kill")].via == "#priced-kill"
    assert rel[("DA.directives.strategy.priced_kill", "DA.memory.lessons.priced_kill")].provenance == "derived:tag"

    # cites: [[IRDM]] and tickers=["IRDM"] → virtual DA.ticker.irdm (created once)
    assert "DA.ticker.irdm" in by_id
    assert by_id["DA.ticker.irdm"].node_type == "ticker" and by_id["DA.ticker.irdm"].owner == "generated"
    assert _keys(edges, "cites") == {
        ("DA.directives.strategy.priced_kill", "DA.ticker.irdm", "cites"),
        ("DA.memory.log.2026_06_29_irdm", "DA.ticker.irdm", "cites"),
        ("DA.ltm.20", "DA.ticker.irdm", "cites"),
    }
    assert sum(1 for n in nodes if n.id == "DA.ticker.irdm") == 1

    # constrains from CONSTRAINS: confirmation_policy → regime_gate, priced_kill exist; extension_cap absent;
    # re_entry_quarantine matches the lesson ignoring _/- (memory lesson exists, rule does not)
    assert _keys(edges, "constrains") == {
        ("DA.code.confirmation_policy", "DA.directives.strategy.regime_gate", "constrains"),
        ("DA.code.confirmation_policy", "DA.directives.strategy.priced_kill", "constrains"),
        ("DA.code.confirmation_policy", "DA.memory.lessons.reentry_quarantine", "constrains"),
        ("DA.code.quarantine_line", "DA.memory.lessons.reentry_quarantine", "constrains"),
    }
    assert all(e.provenance == "authored:code_map" for e in edges if e.edge_type == "constrains")

    # overlaps: the memory lesson and the ltm row share nearly every token
    ov = {(e.source, e.target): e for e in edges if e.edge_type == "overlaps"}
    assert ("DA.memory.lessons.priced_kill", "DA.ltm.20") in ov
    e = ov[("DA.memory.lessons.priced_kill", "DA.ltm.20")]
    assert 0.35 <= e.confidence <= 1.0 and e.provenance == "derived:similarity"
    assert e.confidence == round(jaccard(tokens(by_id["DA.memory.lessons.priced_kill"].body),
                                        tokens(by_id["DA.ltm.20"].body)), 3)
    # overlaps never pair two guideline nodes or two overlay nodes
    for (s, t) in ov:
        assert by_id[s].owner in ("db", "default-file") and by_id[t].owner in ("code", "decider_memory")

    # authored edges are unioned; authored subtype_of is skipped
    assert ("DA.ltm.20", "DA.code.quarantine_line", "enforced_by") in _keys(edges)
    assert ("DA.ltm.20", "DA.root", "subtype_of") not in _keys(edges)

    # every edge carries the stamp; sorted; deduped; valid
    assert all(e.version == STAMP for e in edges)
    assert [(e.source, e.edge_type, e.target) for e in edges] == sorted((e.source, e.edge_type, e.target) for e in edges)
    assert len(_keys(edges)) == len(edges)
    assert validate_graph(nodes, edges, root_id="DA.root") == []


def test_includes_via_appended_when_placeholder_absent_and_skips_empty_fields():
    nodes = [
        _n("DA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.template.system", "DA.root", node_type="template", field="system_prompt", body="Legacy system prompt."),
        _n("DA.directives", "DA.root", node_type="field", body="Be selective."),
        _n("DA.soul", "DA.root", node_type="field", field="soul", body=""),
        _n("DA.memory", "DA.root", node_type="field", field="memory", body=""),
    ]
    edges = derive_edges(nodes, version_stamp=STAMP)
    inc = {(e.target): e for e in edges if e.edge_type == "includes"}
    assert set(inc) == {"DA.directives"}
    assert inc["DA.directives"].via == "appended"


def test_inherited_soul_counts_for_assembly():
    nodes = [
        _n("DA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.template.system", "DA.root", node_type="template", field="system_prompt", body="{strategy_directives}"),
        _n("DA.soul", "DA.root", node_type="field", field="soul", body=""),
        _n("DA.soul.mission", "DA.soul", field="soul", body="## Mission\nInherited text.", owner="default-file",
           status="inherited", compiled="effective-only"),
    ]
    edges = derive_edges(nodes, version_stamp=STAMP)
    assert ("DA.template.system", "DA.soul", "includes") in _keys(edges)


def test_tag_shared_by_more_than_six_nodes_is_not_linked():
    nodes = [_n("DA.root", None, node_type="root", field=None, owner="generated"),
             _n("DA.memory", "DA.root", node_type="field", field="memory")]
    for i in range(7):
        nodes.append(_n(f"DA.memory.log.2026_09_0{i}_regime", "DA.memory", node_type="entry", field="memory",
                        body=f"## 2026-09-0{i} #regime entry {i}", tags=["regime"]))
    edges = derive_edges(nodes, version_stamp=STAMP)
    assert _keys(edges, "related_to") == set()
    nodes.pop()   # six nodes → 15 pairwise edges
    edges = derive_edges(nodes, version_stamp=STAMP)
    assert len(_keys(edges, "related_to")) == 15


def test_resolve_link_order_and_aliases():
    nodes = _small_graph()
    by_id = {n.id: n for n in nodes}
    assert resolve_link("DA.soul.mission", by_id, prefix="DA") == "DA.soul.mission"
    assert resolve_link("Priced_Kill", by_id, prefix="DA") == "DA.directives.strategy.priced_kill"
    assert resolve_link("reentry-quarantine", by_id, prefix="DA") == "DA.memory.lessons.reentry_quarantine"
    assert resolve_link("regime", by_id, prefix="DA") == "DA.directives.strategy.regime_gate"    # tag match
    assert resolve_link("decider", by_id, prefix="DA") == "DA.root"                                # alias
    assert resolve_link("front-run-not-chase", by_id, prefix="DA") is None                         # alias target absent
    assert resolve_link("nonexistent thing", by_id, prefix="DA") is None


def test_validate_graph_reports_problems():
    nodes = [
        _n("DA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.directives", "DA.root", node_type="field"),
        _n("DA.directives.a", "DA.directives.missing"),
        _n("DA.directives.b", "DA.directives.c"),
        _n("DA.directives.c", "DA.directives.b"),
        _n("DA.Bad-Id", "DA.root"),
        _n("SA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.directives", "DA.root", node_type="field"),
    ]
    edges = [
        Edge("DA.directives", "DA.root", "subtype_of"),
        Edge("DA.directives", "DA.root", "subtype_of"),
        Edge("DA.directives", "DA.nowhere", "related_to"),
        Edge("DA.directives", "DA.directives", "cites"),
        Edge("DA.directives", "DA.root", "frobnicates"),
    ]
    problems = validate_graph(nodes, edges, root_id="DA.root")
    text = "\n".join(problems)
    assert "duplicate node id DA.directives" in text
    assert "bad node id 'DA.Bad-Id'" in text
    assert "expected exactly one root" in text
    assert "parent DA.directives.missing does not exist" in text
    assert "parent cycle" in text
    assert "duplicate edge" in text
    assert "target missing" in text
    assert "self-loop" in text
    assert "unknown edge_type" in text
    assert validate_graph(_small_graph(), [], root_id="DA.root") == []


def test_edges_json_roundtrip(tmp_path):
    nodes = _small_graph()
    edges = derive_edges(nodes, version_stamp=STAMP)
    path = tmp_path / "edges.json"
    write_edges_json(path, list(reversed(edges)))
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    records = json.loads(raw)
    assert records == sorted(records, key=lambda r: (r["source_node_id"], r["edge_type"], r["target_node_id"]))
    assert set(records[0]) >= {"source_node_id", "target_node_id", "edge_type", "confidence", "provenance", "version"}
    assert raw.startswith(b"[\n {\n")          # indent=1
    back = read_edges_json(path)
    assert [e.to_record() for e in back] == [e.to_record() for e in edges]
    assert read_edges_json(tmp_path / "absent.json") == []


# ----------------------------------------------------------------------------- v21-shaped graph with the real code nodes
def _v21_like():
    strategy_rules = [
        ("regime_gate", "1. REGIME GATE — read the INDEX REGIME line first. RISK-ON: full rails, up to 3 new BUYs; "
                        "MIXED: at most 2 new BUYs at half size; RISK-OFF: cash is the correct default, at most 1 new BUY "
                        "at half size, only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; no re-entry exceptions."),
        ("extension_cap", "2. EXTENSION CAP — extension ≤5% above the 20d MA at full size, 5-8% at half size and only in RISK-ON."),
        ("priced_kill", "3. PRICED KILL — every BUY reason ends with K:<price>;D:<%>; the kill is binding on the first breach."),
        ("re_entry_quarantine", "4. RE-ENTRY QUARANTINE — no same-ticker re-entry within 3 days of an exit; the QUARANTINE line is binding."),
        ("correlation", "5. CORRELATION — at most two names from the same sector ETF."),
        ("harvest", "6. HARVEST — take +3% winners unless a fresh catalyst justifies holding."),
    ]
    nodes = [
        _n("DA.root", None, node_type="root", field=None, owner="generated"),
        _n("DA.template.system", "DA.root", node_type="template", field="system_prompt",
           body="You are the Decider.\n\n{strategy_directives}"),
        _n("DA.template.user", "DA.root", node_type="template", field="user_prompt_template", body="INPUTS … JSON"),
        _n("DA.directives", "DA.root", node_type="field", body=""),
        _n("DA.directives.ground_truth", "DA.directives", body="## GROUND TRUTH — NON-NEGOTIABLE\nHoldings are truth."),
        _n("DA.directives.strategy", "DA.directives", body="## Current Strategy (2026-09-02)"),
        _n("DA.soul", "DA.root", node_type="field", field="soul", body="# Decider Agent — Soul"),
        _n("DA.soul.mission", "DA.soul", field="soul", body="## Mission\nCompound capital with 1-5 day swings."),
        _n("DA.memory", "DA.root", node_type="field", field="memory", body="---\nagent: decider\n---"),
        _n("DA.memory.lessons", "DA.memory", field="memory", body="## Lessons Learned"),
        _n("DA.memory.lessons.regime", "DA.memory.lessons", node_type="lesson", field="memory", tags=["regime"],
           body="- **#regime** RISK-OFF entries lost; cash is the correct default in RISK-OFF."),
        _n("DA.runtime.inputs", "DA.root", node_type="data", field=None, owner="runtime", body="per-cycle"),
        _n("DA.code", "DA.root", node_type="code", field=None, owner="generated", body=""),
        _n("DA.ltm", "DA.root", node_type="ltm", field=None, owner="decider_memory", body=""),
    ]
    for slug, body in strategy_rules:
        nodes.append(_n(f"DA.directives.strategy.{slug}", "DA.directives.strategy", node_type="rule", body=body))
    fields = {"user_prompt_template": "INPUTS … JSON", "strategy_directives": "x"}
    nodes += code_nodes("DeciderAgent", fields, is_margin_account=False)
    _, rows = ltm_nodes([
        {"id": 20, "content": "RISK-OFF: cash is the correct default; at most 1 new BUY at half size.",
         "kind": "rule", "ticker": None, "weight": 2.0, "active": True, "tags": ["regime"],
         "created_at": datetime(2026, 8, 20, 9, 0), "updated_at": datetime(2026, 8, 20, 9, 0), "source": "feedback"},
    ])
    nodes += rows
    return nodes


def test_v21_like_graph_edges_and_constrains():
    nodes = _v21_like()
    edges = derive_edges(nodes, version_stamp=STAMP)
    assert validate_graph(nodes, edges, root_id="DA.root") == []
    assert _keys(edges, "constrains") == {
        ("DA.code.confirmation_policy", "DA.directives.strategy.regime_gate", "constrains"),
        ("DA.code.confirmation_policy", "DA.directives.strategy.extension_cap", "constrains"),
        ("DA.code.confirmation_policy", "DA.directives.strategy.re_entry_quarantine", "constrains"),
        ("DA.code.confirmation_policy", "DA.directives.strategy.priced_kill", "constrains"),
        ("DA.code.index_regime", "DA.directives.strategy.regime_gate", "constrains"),
        ("DA.code.deploy_policy", "DA.directives.strategy.regime_gate", "constrains"),
        ("DA.code.watchlist_header", "DA.directives.strategy.extension_cap", "constrains"),
        ("DA.code.quarantine_line", "DA.directives.strategy.re_entry_quarantine", "constrains"),
    }
    # the user template includes every DA code node (source order) + ltm + runtime inputs
    inc = [e.target for e in edges if e.edge_type == "includes" and e.source == "DA.template.user"]
    code_ids = [n.id for n in sorted((n for n in nodes if n.owner == "code"), key=lambda n: n.order)]
    assert inc == sorted(code_ids + ["DA.ltm", "DA.runtime.inputs"])
    # the regime rule overlaps the deployment-rule copy it was written from; the ltm row shares the tag
    ov = _keys(edges, "overlaps")
    assert ("DA.directives.strategy.regime_gate", "DA.code.index_regime", "overlaps") in ov
    assert ("DA.memory.lessons.regime", "DA.ltm.20", "overlaps") in ov
    # shared #regime tag → related_to (direction is the sorted id pair)
    assert ("DA.ltm.20", "DA.memory.lessons.regime", "related_to") in _keys(edges, "related_to")
    # nothing pairs a guideline with a template or a code node with a code node
    by_id = {n.id: n for n in nodes}
    for s, t, _ in ov:
        assert by_id[s].owner == "db" and by_id[t].owner in ("code", "decider_memory")
    assert len(BLOCKS_BY_ID) == 19


# ----------------------------------------------------------------------------- decider_memory snapshot
def _rows():
    return [
        {"id": 1, "content": "Never chase a gap-up on stale news.", "kind": "lesson", "ticker": None, "weight": 1.0,
         "active": True, "tags": ["gap-chase"], "created_at": datetime(2026, 7, 1, 8, 0), "updated_at": datetime(2026, 7, 1, 8, 0),
         "source": "feedback"},
        {"id": 2, "content": "IRDM: same-ticker re-entry within 3 days lost twice.", "kind": "mistake", "ticker": "irdm",
         "weight": 1.5, "active": True, "tags": "{reentry,irdm}", "created_at": datetime(2026, 7, 2, 8, 0),
         "updated_at": datetime(2026, 7, 3, 8, 0), "source": "human"},
        {"id": 3, "content": "Old rule retired.", "kind": "rule", "ticker": None, "weight": 3.0, "active": False,
         "tags": None, "created_at": datetime(2026, 6, 1, 8, 0), "updated_at": datetime(2026, 8, 1, 8, 0), "source": "seed"},
        {"id": 4, "content": "Same weight, newer row.", "kind": None, "ticker": None, "weight": 1.0, "active": True,
         "tags": [], "created_at": datetime(2026, 7, 9, 8, 0), "updated_at": datetime(2026, 7, 9, 8, 0), "source": "auto"},
    ]


def test_ltm_nodes_format_like_format_long_term_memory():
    sha, nodes = ltm_nodes(_rows(), injected_limit=2)
    by_id = {n.id: n for n in nodes}
    assert set(by_id) == {"DA.ltm.1", "DA.ltm.2", "DA.ltm.3", "DA.ltm.4"}
    assert by_id["DA.ltm.1"].body == "- [lesson] Never chase a gap-up on stale news."
    assert by_id["DA.ltm.2"].body == "- [mistake] (irdm) IRDM: same-ticker re-entry within 3 days lost twice."
    assert by_id["DA.ltm.4"].body == "- [lesson] Same weight, newer row."          # kind None → 'lesson'
    assert format_memory_line({"content": "x", "kind": "rule", "ticker": "SPY"}) == "- [rule] (SPY) x"
    for n in nodes:
        assert n.parent == "DA.ltm" and n.node_type == "ltm" and n.owner == "decider_memory"
        assert n.compiled == "never" and n.locked is True and n.polarity == "evidence"
        assert set(n.extra) == {"kind", "source", "weight", "ticker", "row_created_at", "row_updated_at", "injected", "active"}
    assert by_id["DA.ltm.3"].status == "inactive" and by_id["DA.ltm.1"].status == "active"
    assert by_id["DA.ltm.2"].tags == ["reentry", "irdm"]                              # Postgres TEXT[] literal
    assert by_id["DA.ltm.2"].tickers == ["IRDM"] and by_id["DA.ltm.2"].extra["ticker"] == "IRDM"
    assert by_id["DA.ltm.2"].extra["row_updated_at"] == "2026-07-03T08:00:00"
    # order: weight desc then created_at desc — inactive rows keep their rank but are never injected
    assert [n.id for n in nodes] == ["DA.ltm.3", "DA.ltm.2", "DA.ltm.4", "DA.ltm.1"]
    assert [n.extra["injected"] for n in nodes] == [False, True, True, False]
    assert len(sha) == 12 and sha == snapshot_sha(_rows())


def test_ltm_snapshot_sha_is_order_independent_and_content_sensitive():
    rows = _rows()
    assert snapshot_sha(rows) == snapshot_sha(list(reversed(rows)))
    changed = [dict(r) for r in rows]
    changed[0]["content"] += "!"
    assert snapshot_sha(changed) != snapshot_sha(rows)
    reweighted = [dict(r) for r in rows]
    reweighted[0]["weight"] = 9.0
    assert snapshot_sha(reweighted) != snapshot_sha(rows)
    # created_at / source are not part of the snapshot identity
    moved = [dict(r) for r in rows]
    moved[0]["created_at"] = datetime(2020, 1, 1)
    moved[0]["source"] = "x"
    assert snapshot_sha(moved) == snapshot_sha(rows)
    assert ltm_nodes([]) == (snapshot_sha([]), [])


def test_ltm_group_node_shape():
    g = ltm_group_node()
    assert g.id == "DA.ltm" and g.parent == "DA.root" and g.owner == "decider_memory" and g.compiled == "never"
