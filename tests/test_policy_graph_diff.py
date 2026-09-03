"""policy_graph.diff — cross-version matching, unified diffs, node history, version kind
(spec section 9, tests item 6). DB-free; real versions come from the fixtures via store.materialize
into tmp_path, synthetic ones are built as in-memory Version objects."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from policy_graph import diff as D
from policy_graph import store
from policy_graph.code_blocks import CODE_SHA, code_nodes
from policy_graph.compile import read_version_dir
from policy_graph.lessons import ltm_nodes
from policy_graph.model import FIELDS, InheritedText, Node, RowMeta, Version

REPO = Path(__file__).resolve().parent.parent
FX = REPO / "tests" / "fixtures" / "policy_graph"
INDEX = json.loads((FX / "INDEX.json").read_text(encoding="utf-8"))
CFG = "cfg_test"
AGENT = "DeciderAgent"
SOUL_DEFAULT = (REPO / "agents" / "decider" / "SOUL.default.md").read_text(encoding="utf-8").strip()


# ----------------------------------------------------------------------------- fixture versions
def fixture_fields(agent: str, version: int) -> tuple:
    fields, entry = {f: None for f in FIELDS}, None
    for e in INDEX:
        if e["agent_type"] == agent and e["version"] == version:
            fields[e["field"]] = (FX / e["file"]).read_bytes().decode("utf-8")
            entry = e
    assert entry is not None
    return fields, entry


def build_version(tmp_path: Path, version: int, fields: dict, entry: dict, *, inherited=None) -> Version:
    meta = RowMeta(prompt_version_id=entry["prompt_version_id"], created_at=datetime.fromisoformat(entry["created_at"]),
                   created_by=entry["created_by"], description=entry.get("description", ""), is_active=False)
    ltm_sha, ln = ltm_nodes([])
    res = store.materialize(tmp_path, AGENT, CFG, version, fields, meta=meta, inherited=inherited or {},
                            code_nodes=code_nodes(AGENT, fields, is_margin_account=False), code_sha=CODE_SHA,
                            ltm_nodes=ln, ltm_sha=ltm_sha, ltm_snapshot="live", is_margin_account=False,
                            materialized_by="test")
    return read_version_dir(res.path)


@pytest.fixture(scope="module")
def decider(tmp_path_factory) -> dict:
    """v0, v18, v19 (soul inherited), v20, v21 from the fixtures; templates shared so they compare equal."""
    tmp = tmp_path_factory.mktemp("diff")
    f21, e21 = fixture_fields(AGENT, 21)
    f20, e20 = fixture_fields(AGENT, 20)
    f19, e19 = fixture_fields(AGENT, 19)
    f18, e18 = fixture_fields(AGENT, 18)
    f0, e0 = fixture_fields(AGENT, 0)
    for f in (f20, f19, f18, f0):
        f["system_prompt"], f["user_prompt_template"] = f21["system_prompt"], f21["user_prompt_template"]
    f18["memory"] = f19["memory"]           # the v18 memory column was not captured; keep memory constant
    inherited = {"soul": InheritedText(text=SOUL_DEFAULT, source_path="agents/decider/SOUL.default.md",
                                       git_sha="54a50e5e", resolution="git-blob-at-created_at")}
    return {
        0: build_version(tmp, 0, f0, e0),
        18: build_version(tmp, 18, f18, e18),
        19: build_version(tmp, 19, f19, e19, inherited=inherited),
        20: build_version(tmp, 20, f20, e20),
        21: build_version(tmp, 21, f21, e21),
    }


# ----------------------------------------------------------------------------- synthetic versions
def _node(id_, body, *, field="strategy_directives", node_type="rule", owner="db", parent=None, title=None):
    return Node(id=id_, agent=AGENT, title=title or id_.rsplit(".", 1)[-1], node_type=node_type,
                parent=parent or id_.rsplit(".", 1)[0], field=field, body=body, owner=owner)


def _version(version: int, nodes: list, *, created_by="prompt_lab", inherited=None, prefix="DA") -> Version:
    fields_meta = {f: {"stored_null": False, "stored_empty": False, "inherited": False} for f in FIELDS}
    for f in (inherited or []):
        fields_meta[f]["inherited"] = True
    manifest = {"schema": 1, "agent_type": AGENT, "prefix": prefix, "config_hash": CFG, "version": version,
                "root_id": f"{prefix}.root", "created_by": created_by, "created_at": f"2026-08-{version + 1:02d}T00:00:00",
                "fields": fields_meta}
    root = Node(id=f"{prefix}.root", agent=AGENT, title="root", node_type="root", parent=None, field=None, body="",
                owner="generated")
    return Version(path=Path(f"/virtual/v{version}"), manifest=manifest, nodes={n.id: n for n in [root] + nodes}, edges=[])


STRAT = "DA.directives.strategy"
N3_BODY = ("3. Every BUY ends with K:<price>;D:<%> — the kill price and the deploy percentage are part of the "
           "decision, not an afterthought; a BUY without them is invalid and gets rejected by the gate.")
PRICED_KILL_BODY = ("3. PRICED KILL — every BUY ends with K:<price>;D:<%> — the kill price and the deploy percentage "
                    "are part of the decision, not an afterthought; a BUY without them is invalid and gets rejected.")


# ----------------------------------------------------------------------------- real fixtures
def test_v20_to_v21(decider):
    d = D.diff_versions(decider[20], decider[21])
    assert "DA.directives.strategy" in d.changed
    for slug in ("regime_gate", "extension_cap", "priced_kill", "re_entry_quarantine", "correlation", "harvest", "n7", "n8"):
        assert f"{STRAT}.{slug}" in d.added, slug
        assert d.per_node[f"{STRAT}.{slug}"].change == "added"
    assert "DA.memory.log.2026_08_27" in d.removed
    assert d.per_node["DA.memory.log.2026_08_27"].change == "removed"
    assert "DA.directives.reminder" not in decider[20].nodes and "DA.directives.reminder" not in decider[21].nodes
    assert "DA.directives.reminder" not in d.per_node
    assert d.source_changed == []
    assert "DA.template.system" in d.same and "DA.template.user" in d.same
    assert "DA.directives.ground_truth" in d.changed + d.same + d.whitespace_only
    # code / ltm / runtime / ticker nodes are never part of the diff
    assert not any(i.startswith(("DA.code", "DA.ltm", "DA.runtime", "DA.ticker")) for i in d.per_node)
    # the manifest recorded the same counts at write time
    delta = decider[21].manifest["delta_vs_prev"]
    assert delta["prev_version"] == 20
    assert (delta["added"], delta["changed"], delta["removed"]) == (len(d.added), len(d.changed), len(d.removed))


def test_v18_to_v19(decider):
    d = D.diff_versions(decider[18], decider[19])
    assert "DA.directives.ground_truth" in d.removed
    assert "DA.directives.reminder" in d.added
    assert decider[19].nodes["DA.directives.reminder"].node_type == "reminder"
    assert d.source_changed == ["soul"]
    soul_ids = [i for i, n in decider[19].nodes.items() if n.field == "soul"]
    assert soul_ids and all(decider[19].nodes[i].owner == "default-file" for i in soul_ids)
    assert all(d.per_node[i].change == "source_changed" for i in soul_ids)
    assert not any(i.startswith("DA.soul") for i in d.added + d.changed + d.removed)
    # memory was held constant → every memory node is 'same'
    mem = [i for i, n in decider[19].nodes.items() if n.field == "memory" and n.owner == "db"]
    assert mem and all(d.per_node[i].change == "same" for i in mem)


def test_version_kind_on_fixtures(decider):
    assert D.version_kind(None, decider[0], 0) == "seed"
    assert D.version_kind(decider[18], decider[19], 0) == "reminder_only"
    assert D.version_kind(decider[19], decider[20], 0) == "policy"
    assert D.version_kind(decider[20], decider[21], 0) == "policy"
    assert D.version_kind(decider[20], decider[21], 1) == "rewrite"         # _prior history → the row was rewritten
    assert D.version_kind(None, decider[21], 0) == "rewrite"
    assert decider[19].manifest["kind"] == "reminder_only"
    assert decider[21].manifest["kind"] == "policy"


def test_unified_diff_shape_on_fixture(decider):
    prev, cur = decider[20].nodes["DA.directives.strategy"], decider[21].nodes["DA.directives.strategy"]
    lines = D.node_unified_diff(prev, cur, prev_label="DA.directives.strategy@v20", cur_label="DA.directives.strategy@v21")
    assert lines[0] == "--- DA.directives.strategy@v20"
    assert lines[1] == "+++ DA.directives.strategy@v21"
    assert lines[2].startswith("@@ ")
    assert all(not l.endswith("\n") for l in lines)
    assert any(l.startswith("+") for l in lines[2:]) and any(l.startswith("-") for l in lines[2:])
    stats = D.diff_stats(lines)
    assert stats["added"] > 0 and stats["removed"] > 0
    assert D.node_unified_diff(None, None, prev_label="a", cur_label="b") == []
    added_only = D.node_unified_diff(None, cur, prev_label="a", cur_label="b")
    assert added_only[:2] == ["--- a", "+++ b"] and not any(l.startswith("-") for l in added_only[2:])


def test_node_history_on_fixtures(decider):
    versions = [decider[v] for v in (18, 19, 20, 21)]
    rows = D.node_history(versions, "DA.directives.ground_truth")
    assert [r["version"] for r in rows] == [18, 20, 21]           # absent in v19 (reminder-only weekly row)
    assert rows[0]["change"] == "added" and rows[0]["actor_kind"] == "human"
    assert rows[1]["change"] == "added" and rows[2]["change"] in ("same", "changed", "whitespace")
    assert rows[2]["actor_kind"] == "claude_code" and rows[2]["created_at"].startswith("2026-09-02")
    assert all(len(r["body_sha256"]) == 64 for r in rows)
    assert D.node_history(versions, "DA.no.such.node") == []
    assert D.node_history(versions, "DA.code.crowd_fade") == []    # overlay nodes have no history


# ----------------------------------------------------------------------------- synthetic matching rules
def test_loose_last_segment_key_matches_reentry_variants():
    prev = _version(1, [_node("DA.memory.lessons", "## Lessons Learned", field="memory", node_type="section", parent="DA.memory"),
                        _node("DA.memory.lessons.re_entry_quarantine", "- **#re-entry-quarantine** two sessions", field="memory", node_type="lesson")])
    cur = _version(2, [_node("DA.memory.lessons", "## Lessons Learned", field="memory", node_type="section", parent="DA.memory"),
                       _node("DA.memory.lessons.reentry_quarantine", "- **#reentry-quarantine** two sessions", field="memory", node_type="lesson")])
    d = D.diff_versions(prev, cur)
    assert d.added == [] and d.removed == [] and d.renamed == []
    nc = d.per_node["DA.memory.lessons.reentry_quarantine"]
    assert nc.change == "changed" and nc.prev_id == "DA.memory.lessons.re_entry_quarantine"
    assert D.loose_key("DA.memory.lessons.re_entry_quarantine") == D.loose_key("DA.memory.lessons.reentry_quarantine")
    assert D.loose_key("DA.a.b_c") != D.loose_key("DA.a_b.c")      # only the last segment is loosened


def test_rename_detection_n3_to_priced_kill_and_unrelated_not_paired():
    prev = _version(1, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"),
                        _node(f"{STRAT}.n3", N3_BODY),
                        _node(f"{STRAT}.n4", "4. Short rule about cash.")])
    cur = _version(2, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"),
                       _node(f"{STRAT}.priced_kill", PRICED_KILL_BODY),
                       _node(f"{STRAT}.harvest", "4. HARVEST — take profit at +3% on the first green session.")])
    d = D.diff_versions(prev, cur)
    assert len(d.renamed) == 1
    old, new, ratio = d.renamed[0]
    assert (old, new) == (f"{STRAT}.n3", f"{STRAT}.priced_kill") and ratio >= 0.85
    nc = d.per_node[new]
    assert nc.change == "renamed" and nc.renamed_from == old and nc.similarity == ratio
    assert new in d.changed                                          # bodies differ → also changed
    assert d.added == [f"{STRAT}.harvest"] and d.removed == [f"{STRAT}.n4"]
    assert D.similarity(N3_BODY, PRICED_KILL_BODY) >= 0.85
    assert D.similarity("4. Short rule about cash.", "4. HARVEST — take profit at +3% on the first green session.") < D.RENAME_RATIO


def test_rename_requires_same_field_and_depth():
    prev = _version(1, [_node(f"{STRAT}.n1", N3_BODY)])
    cur = _version(2, [_node("DA.directives.priced_kill", N3_BODY, node_type="section", parent="DA.directives"),
                       _node("DA.memory.lessons.priced_kill", N3_BODY, field="memory", node_type="lesson")])
    d = D.diff_versions(prev, cur)
    assert d.renamed == []
    assert sorted(d.added) == ["DA.directives.priced_kill", "DA.memory.lessons.priced_kill"]
    assert d.removed == [f"{STRAT}.n1"]


def test_dated_entries_only_rename_within_the_same_date():
    body = "## 2026-08-27 #IRDM\n- entered late, extension 6% above the 20d, killed at -2%"
    prev = _version(1, [_node("DA.memory.log.2026_08_27", body, field="memory", node_type="entry", parent="DA.memory")])
    cur = _version(2, [_node("DA.memory.log.2026_09_01_irdm", body.replace("2026-08-27", "2026-09-01"), field="memory",
                             node_type="entry", parent="DA.memory")])
    d = D.diff_versions(prev, cur)
    assert d.renamed == []
    assert d.added == ["DA.memory.log.2026_09_01_irdm"] and d.removed == ["DA.memory.log.2026_08_27"]
    cur2 = _version(2, [_node("DA.memory.log.2026_08_27_irdm", body + " (revised)", field="memory", node_type="entry",
                              parent="DA.memory")])
    d2 = D.diff_versions(prev, cur2)
    assert d2.renamed and d2.renamed[0][:2] == ("DA.memory.log.2026_08_27", "DA.memory.log.2026_08_27_irdm")


def test_whitespace_only_and_same():
    prev = _version(1, [_node(f"{STRAT}.n1", "1. Never chase.\n2. Fade the crowd."),
                        _node(f"{STRAT}.n2", "2. Same bytes.")])
    cur = _version(2, [_node(f"{STRAT}.n1", "1. Never   chase.\n\n2. Fade the crowd.  "),
                       _node(f"{STRAT}.n2", "2. Same bytes.")])
    d = D.diff_versions(prev, cur)
    assert d.whitespace_only == [f"{STRAT}.n1"] and d.same == [f"{STRAT}.n2"]
    assert d.changed == [] and d.added == [] and d.removed == []
    assert d.per_node[f"{STRAT}.n1"].change == "whitespace"
    assert d.summary() == {"added": 0, "changed": 0, "removed": 0, "renamed": 0, "whitespace": 1, "source_changed": []}


def test_prev_none_marks_everything_added():
    cur = _version(1, [_node(f"{STRAT}.n1", "1. x"), _node("DA.code.x", "code", field=None, owner="code", node_type="code", parent="DA.code")])
    d = D.diff_versions(None, cur)
    assert d.added == [f"{STRAT}.n1"] and d.removed == [] and d.source_changed == []
    assert "DA.code.x" not in d.per_node


def test_source_changed_both_directions():
    stored = _version(1, [_node("DA.soul", "# Soul", field="soul", node_type="field", parent="DA.root"),
                          _node("DA.soul.mission", "## Mission\nstored text", field="soul", node_type="section")])
    inherited = _version(2, [_node("DA.soul", "# Soul", field="soul", node_type="field", parent="DA.root", owner="default-file"),
                             _node("DA.soul.mission", "## Mission\ndefault text", field="soul", node_type="section", owner="default-file")],
                         inherited=["soul"])
    d = D.diff_versions(stored, inherited)
    assert d.source_changed == ["soul"]
    assert d.per_node["DA.soul.mission"].change == "source_changed" and d.changed == [] and d.added == []
    d2 = D.diff_versions(inherited, stored)
    assert d2.source_changed == ["soul"] and d2.per_node["DA.soul.mission"].change == "source_changed"
    assert D.version_kind(stored, inherited, 0) == "policy"


# ----------------------------------------------------------------------------- history along rename chains
def test_node_history_follows_rename_chain():
    v1 = _version(1, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"), _node(f"{STRAT}.n3", N3_BODY)], created_by="init_database")
    v2 = _version(2, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"), _node(f"{STRAT}.priced_kill", PRICED_KILL_BODY)], created_by="claude_code")
    v3 = _version(3, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"), _node(f"{STRAT}.priced_kill", PRICED_KILL_BODY)], created_by="system")
    v4 = _version(4, [_node(STRAT, "## Current Strategy", node_type="section", parent="DA.directives"), _node(f"{STRAT}.priced_kill", PRICED_KILL_BODY + " tightened.")], created_by="prompt_lab")
    rows = D.node_history([v3, v1, v4, v2], f"{STRAT}.priced_kill")      # unordered input
    assert [(r["version"], r["id"], r["change"]) for r in rows] == [
        (1, f"{STRAT}.n3", "added"),
        (2, f"{STRAT}.priced_kill", "renamed"),
        (3, f"{STRAT}.priced_kill", "same"),
        (4, f"{STRAT}.priced_kill", "changed"),
    ]
    assert rows[1]["renamed_from"] == f"{STRAT}.n3"
    assert [r["actor_kind"] for r in rows] == ["seed", "claude_code", "weekly", "human"]
    # asking by the old id walks forward through the same chain
    assert [r["version"] for r in D.node_history([v1, v2, v3, v4], f"{STRAT}.n3")] == [1, 2, 3, 4]


# ----------------------------------------------------------------------------- version_kind rules
def test_version_kind_reminder_only_and_policy_rules():
    base = [_node("DA.directives", "", node_type="field", parent="DA.root"),
            _node("DA.directives.ground_truth", "## GROUND TRUTH\n- Holdings is authoritative.", node_type="section", parent="DA.directives"),
            _node("DA.memory", "# Memory", field="memory", node_type="field", parent="DA.root"),
            _node("DA.memory.log", "## Log", field="memory", node_type="section", parent="DA.memory")]
    v1 = _version(1, base)
    weekly = _version(2, base + [_node("DA.directives.reminder", "Latest Feedback Reminder: fade the open.", node_type="reminder", parent="DA.directives"),
                                 _node("DA.memory.log.2026_08_27", "## 2026-08-27\n- weekly note", field="memory", node_type="entry", parent="DA.memory.log")],
                      created_by="system")
    assert D.version_kind(v1, weekly, 0) == "reminder_only"
    human = _version(3, base + [_node("DA.directives.reminder", "Latest Feedback Reminder: fade the open.", node_type="reminder", parent="DA.directives")],
                     created_by="prompt_lab")
    assert D.version_kind(v1, human, 0) == "reminder_only"          # only the reminder touched, nothing removed
    policy = _version(4, base + [_node("DA.directives.strategy", "## Current Strategy\n- new rule", node_type="section", parent="DA.directives")],
                      created_by="prompt_lab")
    assert D.version_kind(v1, policy, 0) == "policy"
    dropped = _version(5, [n for n in base if n.id != "DA.directives.ground_truth"] +
                       [_node("DA.directives.reminder", "Latest Feedback Reminder: x", node_type="reminder", parent="DA.directives")],
                       created_by="prompt_lab")
    assert D.version_kind(v1, dropped, 0) == "policy"               # a human removing GROUND TRUTH is a policy change
    seed = _version(6, base, created_by="init_database")
    assert D.version_kind(v1, seed, 0) == "seed"
    v0 = _version(0, base, created_by="prompt_lab")
    assert D.version_kind(None, v0, 0) == "seed"
    assert D.version_kind(v1, policy, 2) == "rewrite"
    assert D.version_kind(None, policy, 0) == "rewrite"


def test_norm_body_drops_markers_and_digits():
    assert D.norm_body("## 2026-08-27 #IRDM\n- **#gap-chase** Never chase 5% gaps") == "#irdm never chase #% gaps"
    assert D.norm_body("3. PRICED KILL — K:<price>") == "priced kill — k:<price>"
    assert D.norm_body("") == "" and D.similarity("", "") == 1.0 and D.similarity("a", "") == 0.0
