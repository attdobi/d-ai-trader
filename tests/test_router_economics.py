"""Whole-prompt shadow economics use a frozen cycle and never claim realized savings."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from policy_graph.assembly import Context, assemble
from policy_graph.citations import citable_nodes, ltm_index_lines
from policy_graph.model import Node, Version
from policy_router import economics as e
from policy_router.decisions import DecisionsShadowResult
from policy_router.decisions_log import comparison_panel, record_shadow
from policy_router.nodes import RouterNode
from policy_router.select import select_subgraph


def fixture_capture(**overrides):
    def node(ident, kind, field, body, order):
        return Node(ident, "DeciderAgent", ident.rsplit(".", 1)[-1], kind, None, field, body,
                    sep_after="\n", order=order)
    nodes = [node("DA.directives.stop", "rule", "strategy_directives", "Keep binding priced stops.", 1),
             node("DA.soul.identity", "identity", "soul", "A disciplined trader.", 2),
             node("DA.memory.log.2026_10_20", "entry", "memory", "An optional earlier observation. " * 80, 3),
             node("DA.memory.log.2026_01_01", "entry", "memory", "An old unrelated observation. " * 50, 4)]
    version = Version(Path("/unused"), {"compile_order": {
        "strategy_directives": [nodes[0].id], "soul": [nodes[1].id], "memory": [n.id for n in nodes[2:]]}},
        {n.id: n for n in nodes}, [])
    context = Context(regime="MIXED", today=datetime(2026, 10, 28))
    health = {nodes[0].id: {"90d": {"cited": 10, "closed": 5, "decisive": 4, "win_rate": .5}}}
    template = "Current task. {strategy_directives}"
    out = assemble(version, context, health=health)
    system = e._system(template, out)
    rows = [{"id": 1, "kind": "lesson", "content": "A supplied holding-specific note. " * 70, "ticker": "MSFT"},
            {"id": 2, "kind": "mistake", "content": "A separate unserved note. " * 50, "ticker": None}]
    ltm_health = {"DA.ltm.1": {"90d": {"cited": 4}}}
    actual_rows = rows[:1]
    user = "ACCOUNT numbers and all six summaries stay byte-identical.\n"
    start = len(user)
    user += e._ltm(actual_rows, ltm_health)
    ltm_span = (start, len(user))
    user += "\nWORKING MEMORY stays fixed.\nEXTRA CODE CONTROLS stay fixed."
    start = len(user)
    ids = {s.node_id for s in out.served}
    lines = [f"{i} — {title}" for i, title in citable_nodes(version) if i in ids]
    user += e.INDEX_PREFIX + "\n".join(lines + ltm_index_lines(actual_rows))
    index_span = (start, len(user))
    eligible = {nodes[2].id: "entry", nodes[3].id: "entry", "DA.ltm.1": "ltm", "DA.ltm.2": "ltm"}
    args = dict(graph={"version": version, "context": context, "health": health, "template": template, "override": None},
                system_prompt=system, user_prompt=user, actual_graph_ids=ids, actual_ltm_rows=actual_rows,
                ltm_rows={f"DA.ltm.{r['id']}": r for r in rows}, ltm_health=ltm_health,
                ltm_span=ltm_span, index_span=index_span, eligible=eligible, model="gpt-6.1-sol",
                input_rate=2.0, client_suffix="\\n\\nREASONING DEPTH: HIGH")
    args.update(overrides)
    return e.capture_prompt(**args), args


def result(capture, kept=()):
    nodes = {i: RouterNode(i, kind, "Candidate text not stored in comparison ledger", 40)
             for i, kind in capture.eligible.items()}
    selection = select_subgraph([(i, n.kind, 1 if i in kept else 0, n.chars) for i, n in nodes.items()],
                                tau_min=.5, recall_target=1)
    return DecisionsShadowResult(status="ok", cost_usd=.002, selection=selection, nodes=nodes,
                                 pinned_ids=("DA.directives.stop", "DA.soul.identity"), request_attempted=True)


def test_matched_full_prompt_counts_include_pins_context_indexes_and_tails():
    capture, args = fixture_capture()
    output = result(capture)
    metrics = e.measure(capture, output)
    assert metrics["status"] == "estimated"
    assert metrics["token_method"] in ("o200k_base_text_estimate", e.TOKEN_METHOD)
    assert metrics["token_estimates"]["all_candidates"] > metrics["token_estimates"]["actual_served"]
    assert metrics["potential_input_tokens_saved"] > 0
    assert metrics["realized_input_savings_usd"] == 0
    assert metrics["shadow_incremental_cost_usd"] == .002
    assert metrics["cache_adjusted_savings_usd"] is None
    assert metrics["quality_status"] == "not_evaluated"
    assert metrics["net_input_savings_usd_uncached_estimate"] == pytest.approx(
        metrics["potential_input_tokens_saved"] * 2 / 1_000_000 - .002)
    routed_system, routed_user = capture.render(set())
    assert "Keep binding priced stops." in routed_system and "disciplined trader" in routed_system
    assert args["client_suffix"] in routed_system
    assert "ACCOUNT numbers and all six summaries stay byte-identical." in routed_user
    assert "WORKING MEMORY stays fixed.\nEXTRA CODE CONTROLS stay fixed." in routed_user
    assert e.TAIL_PREFIX in routed_user and "DA.ltm.1" in routed_user
    assert capture.actual_user == args["user_prompt"]


def test_capture_is_immutable_even_if_live_graph_health_rows_change():
    capture, args = fixture_capture()
    output = result(capture)
    before = e.measure(capture, output)
    args["graph"]["version"].nodes["DA.directives.stop"].body = "Changed later policy"
    args["ltm_rows"]["DA.ltm.1"]["content"] = "Changed later memory"
    args["graph"]["health"].clear()
    assert e.measure(capture, output) == before


def test_actual_reconstruction_rejects_plain_memory_tag_or_ambiguous_index():
    _, args = fixture_capture()
    args["user_prompt"] = args["user_prompt"].replace(" ⟨DA.ltm.1 · cited 7d/30d/90d: 0/0/4⟩", "")
    with pytest.raises(ValueError):
        e.capture_prompt(**args)
    _, args = fixture_capture()
    args["index_span"] = args["ltm_span"]
    with pytest.raises(ValueError, match="overlapping"):
        e.capture_prompt(**args)


def test_unknown_pricing_and_cache_never_become_free_or_realized_savings():
    capture, _ = fixture_capture(input_rate=float("nan"))
    metrics = e.measure(capture, result(capture))
    assert metrics["input_rate_usd_per_million"] is None
    assert metrics["gross_input_savings_usd_uncached_estimate"] is None
    assert metrics["net_input_savings_usd_uncached_estimate"] is None
    assert metrics["realized_input_savings_usd"] == 0
    assert e.measure(None, result(capture))["status"] == "unavailable"
    bad = result(capture)
    bad.nodes.pop(next(iter(bad.nodes)))
    assert e.measure(capture, bad)["status"] == "unavailable"


def test_counterfactual_can_cost_more_than_actual_when_it_adds_previously_unserved_context():
    capture, _ = fixture_capture()
    metrics = e.measure(capture, result(capture, set(capture.eligible)))
    assert metrics["potential_input_tokens_saved"] < 0
    assert metrics["gross_input_savings_usd_uncached_estimate"] < 0
    assert metrics["net_input_savings_usd_uncached_estimate"] < -.002


def test_ltm_only_selection_does_not_change_graph_or_its_dropped_diary_tail():
    _, args = fixture_capture()
    args["eligible"] = {i: kind for i, kind in args["eligible"].items() if kind == "ltm"}
    capture = e.capture_prompt(**args)
    system, user = capture.render({"DA.ltm.1"})
    assert system == capture.actual_system
    assert "not tied to today's regime" in system
    assert e.TAIL_PREFIX in user


def test_ledger_has_full_selection_json_and_never_reconstructs_old_rows_from_current_state():
    engine = create_engine("sqlite://")
    capture, _ = fixture_capture()
    output = result(capture, ["DA.ltm.1"])
    metrics = e.measure(capture, output)
    record_shadow(engine, "cfg", 60, "old", output, source_kind="replay")
    record_shadow(engine, "cfg", 60, "new", output, economics=metrics,
                  served_ids=["DA.ltm.1"], source_input_id=150)
    panel = comparison_panel(engine, "cfg")
    assert panel["runs"][1]["economics"]["status"] == "unavailable"
    assert panel["last_cycle"]["economics"] == metrics
    selection = panel["last_cycle"]["selection"]
    assert selection["selected_ids"] == ["DA.ltm.1"]
    assert set(selection["skipped_ids"]) == set(capture.eligible) - {"DA.ltm.1"}
    assert selection["pinned_ids"] == ["DA.directives.stop", "DA.soul.identity"]
    assert panel["totals"]["economics_captured_runs"] == 1
    assert panel["totals"]["economics_unavailable_runs"] == 1
    assert panel["totals"]["realized_input_savings_usd"] == 0
    with engine.connect() as conn:
        raw = str(conn.execute(text("SELECT * FROM policy_router_comparisons")).fetchall())
    assert "ACCOUNT numbers" not in raw and "Candidate text not stored" not in raw


def test_offline_bpe_never_downloads_when_cache_is_missing_or_corrupt(tmp_path, monkeypatch):
    import tiktoken
    monkeypatch.setattr(tiktoken, "get_encoding", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Implicit download")))
    e._offline_encoding.cache_clear()
    assert e._offline_encoding(str(tmp_path)) is None
    cache = tmp_path / hashlib.sha1(e._BPE_URL.encode()).hexdigest()
    cache.write_bytes(b"Corrupt cached vocabulary")
    e._offline_encoding.cache_clear()
    assert e._offline_encoding(str(tmp_path)) is None
    e._offline_encoding.cache_clear()
