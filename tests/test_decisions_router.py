"""Hosted policy scoring is strict, bounded, separately billed and shadow-only."""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from policy_router.decisions import (
    DecisionsSettings, build_request, decisions_cost, parse_usage, route_shadow_cycle,
)
from policy_router.decisions_log import comparison_panel, record_shadow
from policy_router.features import CycleContext
from policy_router.nodes import RouterNode
from policy_router.select import select_subgraph


KEY = "api-secret-sentinel"
CFG = "shadow-tests"


def context():
    return CycleContext(regime="RISK-OFF", holdings=["OWNED"], watchlist=["CAND"],
                        quarantined=["EXIT"], event_block="MACRO WINDOW: YES; FOMC today",
                        summaries=[{"headlines": ["Candidate pullback"], "insights": "Current evidence only"}],
                        today=datetime(2026, 10, 28, 12, 0))


def nodes():
    return [RouterNode("DA.memory.log.2026_10_20", "entry", "A lesson", 40),
            RouterNode("DA.ltm.1", "ltm", "Holding-specific context", 80),
            RouterNode("DA.ltm.2", "ltm", "A second lesson", 60)]


def response(ids=None):
    ids = ids or [n.node_id for n in nodes()]
    return {"id": "decision_test", "model": "gpt-6-luna",
            "answers": [{"name": i, "type": "predicate", "probability": .95} for i in ids],
            "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
                      "output_tokens": 0, "total_tokens": 1000}}


def run(reply=None, settings=None, **kwargs):
    calls = []
    def transport(url, payload, timeout, api_key):
        calls.append((url, payload, timeout, api_key))
        return reply if reply is not None else response()
    result = route_shadow_cycle(settings or DecisionsSettings(ltm_limit=1), context(), nodes(),
                                pinned_policy="Account rails and standing rules.", pinned_ids=["DA.code.opportunity_charter"],
                                today_ids=[n.node_id for n in nodes()], api_key=KEY,
                                transport=transport, **kwargs)
    return result, calls


def test_one_batch_scores_only_optional_nodes_with_standing_policy_as_shared_evidence():
    before = copy.deepcopy(nodes())
    extra = RouterNode("DA.rule.stop", "rule", "Never remove priced kills", 90)
    payload, candidates, phash, qhash = build_request(context(), before + [extra],
                                                     pinned_policy="Protected stops", pinned_ids=[extra.node_id])
    assert [n.node_id for n in candidates] == [n.node_id for n in before]
    assert len(payload["questions"]) == 3
    assert all(q["type"] == "predicate" and "beyond the pinned policy" in q["instructions"] for q in payload["questions"])
    shared = payload["input"][0]["content"][0]
    assert shared["type"] == "input_json"
    assert shared["data"]["pinned_policy"] == "Protected stops"
    assert shared["data"]["cycle"]["holdings"] == ["OWNED"]
    assert "outcomes" not in shared["data"] and "decisions" not in shared["data"]
    assert len(phash) == len(qhash) == 64
    assert payload["prompt_cache_options"] == {"ttl": "30m"}
    assert len(payload["prompt_cache_key"]) <= 64
    assert KEY not in json.dumps(payload)
    assert nodes() == before


def test_hashes_bind_policy_questions_and_context_without_changing_policy_hash_for_new_context():
    a, _, pa, qa = build_request(context(), nodes(), pinned_policy="Stops")
    b, _, pb, qb = build_request(context(), nodes(), pinned_policy="Changed stop")
    ctx = context()
    ctx.regime = "RISK-ON"
    c, _, pc, qc = build_request(ctx, nodes(), pinned_policy="Stops")
    assert pa != pb and qa == qb
    assert pa == pc and qa == qc and a != c


def test_shadow_result_caps_memory_and_cannot_enable_routing():
    result, calls = run()
    assert result.status == "ok" and result.active is False
    assert not hasattr(result, "assembly_override")
    assert len(calls) == 1 and calls[0][0] == "https://api.openai.com/v1/decisions"
    assert result.request_attempted and result.response_id == "decision_test"
    assert result.selection.capped == {"ltm": ["DA.ltm.2"]}
    assert result.selection.include_ids == {"DA.memory.log.2026_10_20", "DA.ltm.1"}
    assert result.chars_today == 180
    assert result.cost_usd == pytest.approx((500 * .1 + 200 * .01 + 300 * .125) / 1_000_000)
    assert result.usage["input_tokens"] == 1000
    assert "uncalibrated" in result.note


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "order", "refusal", "nan", "inf", "negative", "large", "boolean", "string"])
def test_malformed_or_partial_answers_never_create_a_partial_selection(kind):
    reply = response()
    if kind == "missing": reply["answers"].pop()
    elif kind == "duplicate": reply["answers"][1]["name"] = reply["answers"][0]["name"]
    elif kind == "unknown": reply["answers"][0]["name"] = "DA.rule.stop"
    elif kind == "order": reply["answers"].reverse()
    elif kind == "refusal": reply["answers"][0] = {"type": "refusal", "name": reply["answers"][0]["name"]}
    else:
        reply["answers"][0]["probability"] = {"nan": float("nan"), "inf": float("inf"), "negative": -.1,
                                                 "large": 1.1, "boolean": True, "string": ".9"}[kind]
    result, _ = run(reply)
    assert result.status == "fallback" and result.selection is None and result.probabilities == {}
    assert result.request_attempted and result.cost_usd is not None
    assert not result.active


def test_missing_key_never_calls_transport():
    calls = []
    result = route_shadow_cycle(DecisionsSettings(), context(), nodes(), transport=lambda *a: calls.append(a))
    assert result.note == "missing_api_key" and not result.request_attempted and calls == []


def test_transport_errors_do_not_reveal_credentials_or_remote_body():
    def explode(*args):
        raise RuntimeError("Bearer " + KEY + " " + json.dumps(response()))
    result = route_shadow_cycle(DecisionsSettings(), context(), nodes(), api_key=KEY, transport=explode)
    assert result.status == "fallback" and result.request_attempted and result.cost_usd is None
    assert result.note == "transport_or_scoring_error:RuntimeError"
    assert KEY not in result.note


def test_slow_transport_has_a_hard_deadline_and_no_retry():
    calls = []
    def slow(*args):
        calls.append(True)
        time.sleep(.1)
        return response()
    start = time.monotonic()
    result = route_shadow_cycle(DecisionsSettings(timeout_s=.01), context(), nodes(), api_key=KEY, transport=slow)
    assert time.monotonic() - start < .08
    assert result.note == "deadline_exceeded" and result.selection is None
    assert calls == [True]


def test_unsupported_response_model_preserves_usage_but_cannot_guess_its_price():
    reply = response()
    reply["model"] = "unexpected-provider-model"
    result, _ = run(reply)
    assert result.status == "fallback" and result.note == "response_model_mismatch"
    assert result.usage["input_tokens"] == 1000 and result.cost_usd is None


@pytest.mark.parametrize("settings", [DecisionsSettings(model="gpt-6.1-sol"), DecisionsSettings(timeout_s=float("nan")),
                                     DecisionsSettings(recall_target=1.2), DecisionsSettings(ltm_limit=-1)])
def test_invalid_settings_do_not_send_a_request(settings):
    result, calls = run(settings=settings)
    assert result.status == "fallback" and not result.request_attempted and calls == []


def test_duplicate_pinned_and_oversized_candidate_batches_fail_before_network():
    for candidates, pins in ((nodes() + nodes()[:1], ()), (nodes(), ["DA.ltm.1"]),
                              ([RouterNode(f"DA.ltm.{i}", "ltm", "x", 1) for i in range(401)], ())):
        result = route_shadow_cycle(DecisionsSettings(), context(), candidates, pinned_ids=pins, api_key=KEY,
                                    transport=lambda *_: pytest.fail("unexpected request"))
        assert result.status == "fallback" and not result.request_attempted


def test_decisions_output_is_free_and_cached_tokens_are_not_double_counted():
    reply = response()
    reply["usage"]["output_tokens"] = 50
    usage = parse_usage(reply)
    assert decisions_cost(usage) == decisions_cost(parse_usage(response()))
    assert usage["input_tokens"] == usage["uncached_input_tokens"] + usage["cached_input_tokens"] + usage["cache_write_tokens"]
    reply["usage"]["input_tokens_details"]["cache_write_tokens"] = 900
    with pytest.raises(ValueError, match="invalid_cache_usage"):
        parse_usage(reply)


def test_long_context_multiplier_applies_to_entire_input_and_cache_charge():
    usage = {"input_tokens": 272_000, "uncached_input_tokens": 172_000,
             "cached_input_tokens": 50_000, "cache_write_tokens": 50_000}
    base = (172_000 * .1 + 50_000 * .01 + 50_000 * .125) / 1_000_000
    assert decisions_cost(usage) == pytest.approx(base)
    usage.update(input_tokens=272_001, uncached_input_tokens=172_001)
    assert decisions_cost(usage) == pytest.approx(2 * (base + .1 / 1_000_000))


def test_comparison_log_is_config_scoped_and_distinguishes_hypothetical_selection_from_actual_prompt():
    engine = create_engine("sqlite://")
    assert comparison_panel(engine, CFG)["last_cycle"] is None
    result, _ = run()
    local = SimpleNamespace(selection=select_subgraph([(n.node_id, n.kind, .9, n.chars) for n in nodes()], recall_target=1))
    ident = record_shadow(engine, CFG, 59, "cycle-test", result, local_result=local,
                          served_ids=[n.node_id for n in nodes()], source_input_id=148)
    panel = comparison_panel(engine, CFG)
    last = panel["last_cycle"]
    assert last["id"] == ident and last["source_input_id"] == 148 and last["prompt_version"] == 59
    assert last["chars_today"] == 180 and last["chars_selected"] == 120 and last["chars_saved"] == 60
    assert not last["actual_prompt_changed"] and last["disagreements"] == 1
    assert all(n["served_in_prompt"] for n in last["nodes"])
    assert panel["totals"]["request_attempts"] == 1
    assert panel["totals"]["cost_usd"] == result.cost_usd
    assert comparison_panel(engine, "other-config")["last_cycle"] is None
    with engine.connect() as conn:
        raw = str(conn.execute(text("SELECT * FROM policy_router_comparisons")).fetchall())
    assert KEY not in raw and "Holding-specific context" not in raw


def test_unknown_cost_attempts_and_preflight_skips_are_reported_separately():
    engine = create_engine("sqlite://")
    missing = route_shadow_cycle(DecisionsSettings(), context(), nodes())
    failed = route_shadow_cycle(DecisionsSettings(), context(), nodes(), api_key=KEY,
                                transport=lambda *_: (_ for _ in ()).throw(RuntimeError("network failed")))
    record_shadow(engine, CFG, 59, "missing", missing)
    record_shadow(engine, CFG, 59, "failed", failed)
    totals = comparison_panel(engine, CFG)["totals"]
    assert totals["runs"] == 2 and totals["request_attempts"] == 1
    assert totals["unknown_cost_calls"] == 1 and totals["cost_usd"] is None


def test_replays_are_identified_and_unknown_cost_never_masquerades_as_a_complete_total():
    engine = create_engine("sqlite://")
    good, _ = run()
    failed = route_shadow_cycle(DecisionsSettings(), context(), nodes(), api_key=KEY,
                                transport=lambda *_: (_ for _ in ()).throw(RuntimeError("network failed")))
    record_shadow(engine, CFG, 59, "saved-cycle-probe", good, source_input_id=148, source_kind="replay")
    record_shadow(engine, CFG, 59, "current-cycle", failed)
    panel = comparison_panel(engine, CFG)
    assert panel["runs"][1]["source_kind"] == "replay"
    assert panel["totals"]["live_runs"] == 1 and panel["totals"]["replay_runs"] == 1
    assert panel["totals"]["cost_usd"] is None
    assert panel["totals"]["known_cost_usd"] == good.cost_usd
