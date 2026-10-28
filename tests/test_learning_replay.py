"""Paired replays freeze cases/context, isolate outcomes, and cannot execute trades."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

from policy_graph import inputs
from policy_graph import learning_replay as R
from policy_graph.learning_replay_client import make_openai_runner, usage_cost

CFG = "learning-test"
OLD = {
    "system_prompt": "SYSTEM\n{strategy_directives}", "user_prompt_template": "Quote: {summaries}",
    "soul": "## Mission\nFind controlled opportunities.\n",
    "strategy_directives": "## Current Strategy\n1. REGIME GATE — Half size in RISK-OFF.\n2. PRICED KILL — Use supplied stop.\n",
    "memory": "## Lessons\nAvoid chasing.\n",
}
NEW = {**OLD, "strategy_directives": OLD["strategy_directives"].replace("Half size", "Quarter size")}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    inputs.ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE prompt_versions (
            id INTEGER PRIMARY KEY, config_hash TEXT, agent_type TEXT, version INTEGER,
            system_prompt TEXT, user_prompt_template TEXT, soul TEXT, strategy_directives TEXT,
            memory TEXT, created_at TIMESTAMP)"""))
    insert_policy(engine, CFG, 1, OLD)
    insert_policy(engine, CFG, 2, NEW)
    yield engine
    engine.dispose()


def insert_policy(db, cfg, version, fields):
    with db.begin() as conn:
        conn.execute(text("""INSERT INTO prompt_versions
            (config_hash,agent_type,version,system_prompt,user_prompt_template,soul,strategy_directives,memory,created_at)
            VALUES (:h,'DeciderAgent',:v,:system_prompt,:user_prompt_template,:soul,:strategy_directives,:memory,'2026-10-01 12:00:00')"""),
            {"h": cfg, "v": version, **fields})


def saved(db, *, cfg=CFG, model="gpt-6.1-sol", effort="high", version=1, annotated=True, context=None):
    row = R._row(db, cfg, version)
    if annotated:
        fields, entries = R._render_full(row, {"system_prompt": "⟨DA.fake⟩", "user_prompt": ""})
        index = R.INDEX_MARKER + "\n".join(f"{i} — {t}" for i, t in entries.items())
        index += "\nDA.code.charter — Code charter\nDA.ltm.4 — Frozen long-term row"
    else:
        fields = {k: row[f].strip("\n") for k, f in R.FIELD_KEYS.items()}
        index = ""
    system = OLD["system_prompt"].replace("{strategy_directives}", fields["directives"])
    system += "\n\nIDENTITY\n" + fields["soul"] + "\n\nMEMORY\n" + fields["memory"]
    system += "\n\nFROZEN CODE: must preserve this text verbatim."
    user = "Frozen quote AAA42, BBB13; headline as of October 2.\n\n" + index
    ident = inputs.record_input(db, cfg, run_id="run-" + str(len(inputs.load_inputs(db, cfg, 'x'))),
                                prompt_version=version, system_prompt=system, user_prompt=user,
                                policy=fields, context=context or {"watchlist": ["AAA", "BBB"], "regime": "RISK-OFF"},
                                model=model, reasoning_effort=effort, decided_at="2026-10-02 11:00:00")
    inputs.record_reply(db, ident, {"decisions": [{"ticker": "AAA", "action": "buy", "reason": "Original real decision"}]})
    return ident


def cases(ident, *, cfg=CFG):
    return [{"id": i, "config_hash": cfg, "input_id": ident, "run_id": "run-0", "prompt_version": 1,
             "ticker": ticker, "observed_at": "2026-10-02T18:00:00+00:00", "coverage": "prospective_screener",
             "eligible_for_recall": True, "action": "BUY" if ticker == "AAA" else "PASS", "features": {"regime": "RISK-OFF"},
             "outcomes": {"3": {"status": "matured", "entry_date": "2026-10-05", "exit_date": "2026-10-07",
                                  "horizon": 3, "side_cost_bps": 10, "calendar_id": "nyse-test", "execution": "next_session_open_to_horizon_close",
                                  "net_return_pct": value, "label": "winner" if value > 0 else "loser",
                                  "spec_id": "frozen-session-spec"}}}
            for i, (ticker, value) in enumerate((("AAA", 4.0), ("BBB", -2.0)), 1)]


def runner(request):
    action = "PASS" if request["side"] == "incumbent" else "BUY"
    return {"reply": {"decisions": [{"ticker": "AAA", "action": action, "reason": "Replay response", "cited": ["DA.directives.strategy.regime_gate"]}],
                      "considered": [{"ticker": "BBB", "verdict": "pass", "why": "Skip"}]},
            "model": request["model"], "reasoning_effort": request["reasoning_effort"], "cost_usd": .001,
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def test_preview_is_read_only_and_public(db):
    ident = saved(db)
    result = R.preview_comparison(db, CFG, [ident], 2, cases=cases(ident))
    assert result["compatible"] and result["model_calls"] == 2
    assert result["case_count"] == result["prospective_case_count"] == 2
    assert result["changed_ids"] == ["DA.directives.strategy.regime_gate"]
    assert not inspect(db).has_table("policy_learning_replays")
    assert "Frozen quote" not in json.dumps(result)
    assert "system_prompt" not in json.dumps(result)


def test_same_frozen_context_and_model_two_recomputed_sides_no_outcomes_to_runner(db):
    ident = saved(db)
    called = []
    def collect(request):
        called.append(copy.deepcopy(request))
        assert "outcomes" not in request and "net_return" not in json.dumps(request)
        return runner(request)
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=collect, cases=cases(ident))
    assert result["status"] == "ok" and result["model_calls"] == 2
    assert [r["side"] for r in called] == ["incumbent", "candidate"]
    assert called[0]["user_prompt"] == called[1]["user_prompt"]
    assert "Half size" in called[0]["system_prompt"] and "Quarter size" in called[1]["system_prompt"]
    assert all("FROZEN CODE: must preserve" in r["system_prompt"] for r in called)
    assert called[0]["model"] == called[1]["model"] == "gpt-6.1-sol"
    assert all(r["reasoning_effort"] == "high" for r in called)
    assert result["action_flips"] == 1 and result["cost_usd"] == pytest.approx(.002)
    aaa = result["cases"][0]
    assert (aaa["observed_action"], aaa["incumbent_action"], aaa["candidate_action"]) == ("BUY", "PASS", "BUY")
    assert result["metrics"]["comparable"] == 2 and not result["metrics"]["measurable"]
    assert result["metrics"]["candidate"]["recall"] == 1 and result["metrics"]["incumbent"]["recall"] == 0


def test_schema_idempotent_public_results_config_scoped_and_no_prompt_leak(db):
    ident = saved(db)
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=runner, cases=cases(ident))
    R.ensure_schema(db)
    assert R.list_replays(db, "other") == []
    with pytest.raises(R.ReplayError, match="configuration"):
        R.get_replay(db, "other", result["id"])
    assert len(R.list_replays(db, CFG)) == 1
    public = json.dumps(result) + json.dumps(R.list_replays(db, CFG))
    assert "Frozen quote" not in public and "FROZEN CODE" not in public and "raw_reply" not in public
    with db.connect() as conn:
        audit = conn.execute(text("SELECT * FROM policy_learning_replay_calls")).mappings().all()
    assert len(audit) == 2 and "FROZEN CODE" in audit[0]["system_prompt"]
    assert audit[0]["request_hash"] != audit[1]["request_hash"]


@pytest.mark.parametrize("mutation,expected", [
    ("duplicate_span", "exactly once"), ("missing_span", "exactly once"),
    ("bad_body", "differs"), ("missing_index", "guideline index"),
])
def test_ambiguous_or_modified_source_fails_before_model_calls(db, mutation, expected):
    ident = saved(db)
    with db.begin() as conn:
        row = conn.execute(text("SELECT * FROM decider_inputs WHERE id=:i"), {"i": ident}).mappings().one()
        system, user = row["system_prompt"], row["user_prompt"]
        if mutation == "duplicate_span":
            system += row["policy_memory"]
        elif mutation == "missing_span":
            system = system.replace(row["policy_memory"], "MISSING")
        elif mutation == "bad_body":
            system = system.replace("Half size", "Unknown size")
            conn.execute(text("UPDATE decider_inputs SET policy_directives=REPLACE(policy_directives,'Half size','Unknown size') WHERE id=:i"), {"i": ident})
        else:
            user = "No index captured"
        conn.execute(text("UPDATE decider_inputs SET system_prompt=:s,user_prompt=:u WHERE id=:i"), {"i": ident, "s": system, "u": user})
    preview = R.preview_comparison(db, CFG, [ident], 2)
    assert not preview["compatible"] and expected in preview["errors"][0]
    with pytest.raises(R.ReplayError):
        R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=lambda _: pytest.fail("unexpected call"))


def test_template_changes_and_cross_config_source_rejected(db):
    ident = saved(db)
    assert not R.preview_comparison(db, "other", [ident], 2)["compatible"]
    with db.begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET user_prompt_template='Different {summaries}' WHERE version=2"))
    result = R.preview_comparison(db, CFG, [ident], 2)
    assert not result["compatible"] and "user_prompt_template changed" in result["errors"][0]


def test_added_rule_requires_declared_full_policy_and_indexes_preserve_code_ltm(db):
    ident = saved(db)
    insert_policy(db, CFG, 3, {**NEW, "strategy_directives": NEW["strategy_directives"] + "3. EVENT GATE — Check macro events.\n"})
    result = R.preview_comparison(db, CFG, [ident], 3)
    assert not result["compatible"] and "full_policy" in result["errors"][0]
    calls = []
    def collect(request):
        calls.append(copy.deepcopy(request))
        return runner(request)
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=3, assembly_mode="full_policy", runner=collect)
    assert result["status"] == "ok" and result["assembly_mode"] == "full_policy"
    assert "EVENT GATE" not in calls[0]["system_prompt"] and "EVENT GATE" in calls[1]["system_prompt"]
    assert "DA.directives.strategy.event_gate —" not in calls[0]["user_prompt"]
    assert "DA.directives.strategy.event_gate —" in calls[1]["user_prompt"]
    assert all("DA.code.charter — Code charter" in r["user_prompt"] and "DA.ltm.4 — Frozen long-term row" in r["user_prompt"] for r in calls)
    assert all("Frozen quote AAA42" in r["user_prompt"] for r in calls)
    assert result["metrics"]["comparable"] == 0  # reconstructed cases do not invent paper labels


def test_stale_preview_hash_blocks_before_schema_and_calls(db):
    ident = saved(db)
    data = cases(ident)
    preview = R.preview_comparison(db, CFG, [ident], 2, cases=data)
    data[0]["outcomes"]["3"]["net_return_pct"] = 5.0
    with pytest.raises(R.ReplayError, match="changed since preview"):
        R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=lambda _: pytest.fail("unexpected call"),
                         cases=data, expected_cohort_hash=preview["cohort_hash"])
    assert not inspect(db).has_table("policy_learning_replays")


def test_frozen_cases_survive_mutation_during_calls_and_runner_cannot_mutate_requests(db):
    ident = saved(db)
    data = cases(ident)
    def mutate(request):
        data[0]["outcomes"]["3"]["net_return_pct"] = -999
        answer = runner(request)
        request["system_prompt"] = "MUTATED"
        return answer
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=mutate, cases=data)
    assert result["cases"][0]["outcomes"]["3"]["net_return_pct"] == 4
    with db.connect() as conn:
        assert "MUTATED" not in conn.execute(text("SELECT system_prompt FROM policy_learning_replay_calls LIMIT 1")).scalar_one()


def test_mixed_models_need_explicit_same_model_override_and_call_budget(db):
    a, b = saved(db), saved(db, model="gpt-6-luna", effort="low")
    assert not R.preview_comparison(db, CFG, [a, b], 2)["compatible"]
    assert not R.preview_comparison(db, CFG, [a, b], 2, model="gpt-6-luna", reasoning_effort="low", max_calls=2)["compatible"]
    result = R.preview_comparison(db, CFG, [a, b], 2, model="gpt-6-luna", reasoning_effort="low", max_calls=4)
    assert result["compatible"] and result["model_calls"] == 4


@pytest.mark.parametrize("failure", ["exception", "wrong_model", "wrong_effort", "bad_json", "missing_metadata"])
def test_errors_never_become_pass_or_measured_losses(db, failure):
    ident = saved(db)
    def broken(request):
        if failure == "exception":
            raise RuntimeError("sensitive request text must not be logged")
        answer = runner(request)
        if failure == "wrong_model":
            answer["model"] = "different-model"
        elif failure == "wrong_effort":
            answer["reasoning_effort"] = "low"
        elif failure == "bad_json":
            answer["reply"] = "non JSON sensitive text"
        else:
            answer.pop("model")
        return answer
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=broken, cases=cases(ident))
    assert result["status"] == "error" and result["errors"] == 2
    assert result["metrics"]["comparable"] == 0 and result["action_flips"] == 0
    assert all(c["candidate_action"] == c["incumbent_action"] == "NOT_ASSESSED" for c in result["cases"])
    assert "sensitive request text" not in json.dumps(result)


def test_parse_actions_requires_actual_assessment_and_keeps_decision_precedence():
    assert R.parse_actions({"decisions": []}) == {}
    result = R.parse_actions({"decisions": [{"ticker": "AAA", "action": "BUY"}],
                              "considered": [{"ticker": "AAA", "verdict": "pass"}, {"ticker": "BBB", "verdict": "reject"},
                                             {"ticker": "CCC", "verdict": "unknown"}]})
    assert result["AAA"]["action"] == "BUY" and result["BBB"]["action"] == "PASS" and "CCC" not in result
    with pytest.raises(R.ReplayError):
        R.parse_actions({"decisions": [{"ticker": "AAA", "action": "buy"}, {"ticker": "AAA", "action": "sell"}]})


def test_paired_metrics_dedup_overlap_unknowns_and_mixed_specs():
    data = cases(1)
    for c in data:
        c.update(source_input_id=1, incumbent_status="ok", candidate_status="ok", incumbent_action="PASS", candidate_action="BUY")
    data.append(copy.deepcopy(data[0]))
    data[-1]["source_input_id"] = 2
    result = R.paired_metrics(data)
    assert result["comparable"] == 2 and result["excluded"] == 1
    assert result["candidate"]["precision"] == .5 and result["candidate"]["fpr"] == 1
    assert result["candidate"]["recall"] == 1
    assert result["candidate"]["paper_pnl_per_1000_tickets"] == pytest.approx(20)
    data[1]["outcomes"]["3"]["spec_id"] = "different-costs"
    result = R.paired_metrics(data)
    assert result["comparable"] == 0 and result["candidate"] is None


def test_lazy_openai_adapter_preserves_settings_caps_and_logs_separate_agent(db):
    calls, factories = [], []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model="gpt-6.1-sol", choices=[SimpleNamespace(message=SimpleNamespace(content='{"decisions":[]}'), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200, total_tokens=1200,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0), completion_tokens_details=SimpleNamespace(reasoning_tokens=100)))
    def factory(**kwargs):
        factories.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapted = make_openai_runner(engine=db, config_hash=CFG, max_completion_tokens=2048, client_factory=factory,
                                 pricing={"gpt-6.1-sol": {"input": 2, "output": 10}})
    assert factories == calls == []
    request = {"source_input_id": 1, "side": "candidate", "model": "gpt-6.1-sol", "reasoning_effort": "high",
               "system_prompt": "frozen system", "user_prompt": "frozen user"}
    result = adapted(request)
    assert factories == [{"max_retries": 0, "timeout": 60.0, "base_url": "https://api.openai.com/v1"}]
    assert calls[0] == {"model": "gpt-6.1-sol", "messages": [{"role": "system", "content": "frozen system"},
        {"role": "user", "content": "frozen user"}], "max_completion_tokens": 2048, "store": False, "reasoning_effort": "high"}
    assert result["cost_usd"] == pytest.approx(.004)
    with db.connect() as conn:
        row = conn.execute(text("SELECT * FROM api_usage")).mappings().one()
    assert row["agent_type"] == "PolicyReplayAgent" and row["config_hash"] == CFG and row["cost_usd"] == pytest.approx(.004)


def test_cost_estimate_keeps_missing_cache_prices_unknown():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "cached_input_tokens": 500}
    assert usage_cost("unknown", usage, {}) is None
    assert usage_cost("m", usage, {"m": {"input": 2, "output": 10}}) is None
    assert usage_cost("m", usage, {"m": {"input": 2, "output": 10, "cached_input": .2}}) == pytest.approx(.0021)
    assert usage_cost("m", {**usage, "cached_input_tokens": 2000}, {"m": {"input": 2, "output": 10}}) is None


@pytest.mark.parametrize("action", ["HOLD", "SELL", "NOT_ASSESSED"])
def test_hold_sell_and_unassessed_never_expand_pass_denominator(action):
    data = cases(1)
    for c in data:
        c.update(source_input_id=1, incumbent_status="ok", candidate_status="ok", incumbent_action="PASS", candidate_action=action)
    result = R.paired_metrics(data)
    assert result["comparable"] == 0 and result["candidate"]["recall"] is None


def test_alias_can_resolve_to_one_dated_snapshot_but_not_change_between_sides(db):
    ident = saved(db)
    def same_snapshot(request):
        answer = runner(request)
        answer["model"] = request["model"] + "-2026-10-01"
        return answer
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=same_snapshot)
    assert result["status"] == "ok" and result["actual_model"] == "gpt-6.1-sol-2026-10-01"
    def different_snapshot(request):
        answer = runner(request)
        answer["model"] = request["model"] + ("-2026-10-01" if request["side"] == "incumbent" else "-2026-10-02")
        return answer
    result = R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, runner=different_snapshot, cases=cases(ident))
    assert result["status"] == "error" and result["actual_model"] is None
    assert result["metrics"]["comparable"] == 0 and result["cost_usd"] == pytest.approx(.002)


@pytest.mark.parametrize("credential", ["sk-" + "x" * 30, "Authorization: Bearer private-value"])
def test_credential_shaped_source_fails_without_echo_or_calls(db, credential):
    ident = saved(db)
    with db.begin() as conn:
        conn.execute(text("UPDATE decider_inputs SET user_prompt=:p WHERE id=:i"), {"i": ident, "p": credential})
    preview = R.preview_comparison(db, CFG, [ident], 2)
    assert not preview["compatible"] and "credential-shaped" in preview["errors"][0]
    assert credential not in json.dumps(preview)
    with pytest.raises(R.ReplayError):
        R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2,
                         runner=lambda _: pytest.fail("credential must not reach runner"))


def test_matching_spec_names_do_not_hide_different_cost_conventions():
    data = cases(1)
    for c in data:
        c.update(source_input_id=1, incumbent_status="ok", candidate_status="ok", incumbent_action="PASS", candidate_action="BUY")
    data[1]["outcomes"]["3"]["side_cost_bps"] = 20
    result = R.paired_metrics(data)
    assert result["comparable"] == 0 and result["candidate"] is None


def test_no_case_context_blocks_empty_paid_comparison(db):
    ident = saved(db, context={"watchlist": []})
    result = R.preview_comparison(db, CFG, [ident], 2, cases=[])
    assert not result["compatible"] and "no audited candidate" in result["errors"][0]


@pytest.mark.parametrize("early_failure", ["unassessed", "missing_outcome", "replay_error"])
def test_first_episode_reserved_before_assessment_or_maturity_filters(early_failure):
    first = cases(1)[0]
    first.update(source_input_id=1, incumbent_status="ok", candidate_status="ok", incumbent_action="PASS", candidate_action="PASS")
    later = copy.deepcopy(first)
    later.update(id=2, source_input_id=2, observed_at="2026-10-05T18:00:00+00:00", incumbent_action="BUY", candidate_action="BUY")
    later["outcomes"]["3"].update(entry_date="2026-10-06", exit_date="2026-10-08", net_return_pct=9.0)
    if early_failure == "unassessed":
        first["incumbent_action"] = "NOT_ASSESSED"
    elif early_failure == "missing_outcome":
        first["outcomes"] = {}
    else:
        first["candidate_status"] = "error"
    result = R.paired_metrics([later, first])
    assert result["prospective_cases"] == 2 and result["episodes"] == 1 and result["deduplicated"] == 1
    assert result["comparable"] == 0 and result["excluded"] == 2
    assert result["candidate"]["buys"] == 0 and result["candidate"]["recall"] is None


@pytest.mark.parametrize("mode", R.MODES)
def test_rewritten_unedited_incumbent_rule_in_both_rows_is_incompatible(db, mode):
    ident = saved(db)
    # The proposed edit concerns REGIME GATE. Mutating the unrelated PRICED KILL
    # in BOTH stored rows must not let a candidate hash describe new text while
    # the replay still serves the old captured text.
    with db.begin() as conn:
        conn.execute(text("""UPDATE prompt_versions SET strategy_directives=
            REPLACE(strategy_directives,'Use supplied stop.','Widen every stop.') WHERE config_hash=:h"""), {"h": CFG})
    preview = R.preview_comparison(db, CFG, [ident], 2, assembly_mode=mode)
    assert not preview["compatible"] and "captured incumbent body" in preview["errors"][0]
    with pytest.raises(R.ReplayError, match="captured incumbent body"):
        R.run_comparison(db, CFG, source_input_ids=[ident], candidate_version=2, assembly_mode=mode,
                         runner=lambda _: pytest.fail("rewritten history must fail before a model call"))
    assert not inspect(db).has_table("policy_learning_replays")


@pytest.mark.parametrize("mode", R.MODES)
def test_rewritten_unchanged_flat_field_is_incompatible(db, mode):
    ident = saved(db, annotated=False)
    with db.begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET soul='Rewritten mission' WHERE config_hash=:h"), {"h": CFG})
    preview = R.preview_comparison(db, CFG, [ident], 2, assembly_mode=mode)
    assert not preview["compatible"] and "captured incumbent soul differs" in preview["errors"][0]


def test_rewritten_untagged_field_preamble_is_incompatible(db):
    before = {**OLD, "strategy_directives": "Original preamble.\n\n" + OLD["strategy_directives"]}
    after = {**before, "strategy_directives": before["strategy_directives"].replace("Half size", "Quarter size")}
    insert_policy(db, CFG, 10, before)
    insert_policy(db, CFG, 11, after)
    ident = saved(db, version=10)
    with db.begin() as conn:
        conn.execute(text("""UPDATE prompt_versions SET strategy_directives=
            REPLACE(strategy_directives,'Original preamble.','Rewritten preamble.') WHERE version IN (10,11)"""))
    preview = R.preview_comparison(db, CFG, [ident], 11)
    assert not preview["compatible"] and "preamble differs" in preview["errors"][0]
