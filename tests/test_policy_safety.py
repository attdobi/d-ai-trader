"""Regressions for the learned regime/macro cash lock, without live config or APIs."""
from __future__ import annotations

import ast
import json
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from policy_safety import (
    OPPORTUNITY_CHARTER, PolicyOpportunityError, blanket_entry_vetoes, feedback_policy_violations,
    opportunity_system_prompt, safe_feedback_context, validate_policy_opportunities,
)

ROOT = Path(__file__).resolve().parents[1]
REGIME = "1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise fall through."
MACRO = "9. EVENT GATE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN pass. Otherwise next gate."


@pytest.mark.parametrize("rule", [
    REGIME, MACRO,
    "2. RISK-OFF — IF INDEX REGIME is RISK-OFF THEN pass. Otherwise next gate.",
    "2. EVENT — IF the EVENT CALENDAR MACRO WINDOW flag is active THEN pass without a new BUY. Otherwise next gate.",
    "3. EVENT — IF EVENT CALENDAR for a new BUY shows MACRO WINDOW flag 1 THEN pass. Otherwise next gate.",
    "When risk off, no new buys.", "RISK-OFF — hold cash.",
    "In RISK-OFF, reject all new buys.", "Hold cash during RISK-OFF.",
    "IF MACRO WINDOW=YES THEN no new entries.",
    'New rule: "IF INDEX REGIME is RISK-OFF THEN pass."',
    json.dumps(REGIME),
    json.dumps({"rule": MACRO}),
])
def test_observed_blanket_vetoes_are_detected(rule):
    assert blanket_entry_vetoes(rule)


@pytest.mark.parametrize("rule", [
    "IF INDEX REGIME is RISK-OFF THEN half size. Otherwise next gate.",
    "RISK-OFF: cash default; at most 1 half-size BUY with D <=2%.",
    "IF RISK-OFF and D >2% THEN pass.",
    "IF MACRO WINDOW: YES and no supplied priced kill THEN pass.",
    "IF earnings are within 2 sessions THEN pass.",
    "IF numeric D is missing or D >1.3% THEN PASS.",
    'The retired rule "IF INDEX REGIME is RISK-OFF THEN pass" caused a cash lock.',
    'Historical: IF INDEX REGIME is RISK-OFF THEN pass.',
    'Retired: IF EVENT CALENDAR shows MACRO WINDOW: YES THEN pass.',
    '`IF RISK-OFF THEN pass` was superseded by selective half-size entries.',
    "RISK-OFF entries lost $24 over six campaigns; compare candidate outcomes.",
    OPPORTUNITY_CHARTER,
    "Never hold cash in RISK-OFF.",
    "Do not pass all new buys in RISK-OFF.",
])
def test_selective_entries_hard_gates_and_historical_evidence_survive(rule):
    assert blanket_entry_vetoes(rule) == []


def _method(path, name, namespace):
    """Exercise real methods without importing config or creating tracker tables."""
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("feedback", [
    {"decider_rules": [REGIME], "summarizer_feedback": "Surface pullback candidates."},
    {"decider_feedback": MACRO},
    {"decider_feedback": {"rule": REGIME}},
    {"summarizer_rules": ["When risk off, no new buys."]},
])
def test_weekly_quarantine_precedes_every_policy_or_memory_write(feedback):
    calls = []
    tracker = SimpleNamespace(
        _is_config_in_auto_mode=lambda cfg: True,
        _build_reminder_block=lambda *a: calls.append("reminder"),
        _next_memory_text=lambda *a: calls.append("next memory"),
        _update_strategy_directives_for_config=lambda *a, **kw: calls.append("version write"),
        _update_agent_memory=lambda *a, **kw: calls.append("memory write"),
    )
    method = _method("feedback_agent.py", "_auto_generate_prompts_from_feedback_for_config",
                     {"feedback_policy_violations": feedback_policy_violations})
    method(tracker, feedback, 123, "test-config")
    assert calls == []


def test_weekly_selective_feedback_still_updates_policy_and_memory():
    calls = []
    tracker = SimpleNamespace(
        _is_config_in_auto_mode=lambda cfg: True,
        _build_reminder_block=lambda *a: ("reminder", ["IF RISK-OFF THEN half size."]),
        _next_memory_text=lambda *a: "new memory",
        _update_strategy_directives_for_config=lambda *a, **kw: calls.append(("version", kw)),
        _update_agent_memory=lambda *a, **kw: calls.append(("memory", kw)),
    )
    method = _method("feedback_agent.py", "_auto_generate_prompts_from_feedback_for_config",
                     {"feedback_policy_violations": feedback_policy_violations})
    method(tracker, {"decider_rules": ["IF RISK-OFF THEN half size."]}, 124, "test-config")
    assert [c[0] for c in calls] == ["version", "memory"]
    assert calls[0][1]["memory"] == "new memory"
    assert calls[1][1]["write_prompt_row"] is False


def test_direct_feedback_cannot_bypass_quarantine_and_raw_record_is_unchanged():
    raw = {"rule": MACRO}
    assert "withheld" in safe_feedback_context(raw)
    assert raw == {"rule": MACRO}
    safe = "RISK-OFF: evaluate an oversold reversal at half size."
    assert safe_feedback_context(safe) == safe
    assert "withheld" in safe_feedback_context(json.dumps({"rule": MACRO}))
    assert "withheld" in safe_feedback_context(json.dumps(REGIME))
    assert feedback_policy_violations({"decider_rules": json.dumps([REGIME])})


def test_ltm_insert_is_blocked_before_database_access():
    calls = []
    method = _method("decider_memory.py", "add_memory", {
        "blanket_entry_vetoes": blanket_entry_vetoes,
        "logger": logging.getLogger("test-policy-safety"),
        "engine": SimpleNamespace(begin=lambda: calls.append("database access")),
    })
    method("test-config", REGIME, kind="rule")
    assert calls == []


def test_legacy_ltm_bans_are_withheld_and_good_rows_remain_citable():
    method = _method("decider_memory.py", "format_long_term_memory", {
        "blanket_entry_vetoes": blanket_entry_vetoes,
    })
    rows = [{"id": 24, "content": REGIME}, {"id": 42, "content": MACRO},
            {"id": 43, "content": "Use half size in RISK-OFF.", "kind": "rule"}]
    out = method(rows, cite_tag=lambda m: f" ⟨DA.ltm.{m['id']}⟩")
    assert "DA.ltm.43" in out and "DA.ltm.24" not in out and "DA.ltm.42" not in out
    assert "OBEY" not in out and "subordinate" in out
    assert method(rows[:2]) == ""


@pytest.mark.parametrize("agent", ["DeciderAgent", "FeedbackAgent", "SummarizerAgent"])
def test_policy_activation_lint_sees_nested_rules_and_permits_history(agent):
    with pytest.raises(PolicyOpportunityError, match="blanket regime/macro"):
        validate_policy_opportunities(agent, {"strategy_directives": REGIME})
    validate_policy_opportunities(agent, {"memory": 'Retired: ' + REGIME,
                                         "strategy_directives": "IF RISK-OFF THEN half size."})


@pytest.mark.parametrize("base", ["Flat stored policy", "Graph-assembled policy"])
def test_code_owned_charter_follows_both_policy_paths(base):
    out = opportunity_system_prompt(base)
    assert out == base + "\n\n" + OPPORTUNITY_CHARTER
    assert "Never force a trade" in out and "earnings exclusions" in out
    ask = next(n for n in ast.walk(ast.parse((ROOT / "decider_agent.py").read_text()))
               if isinstance(n, ast.FunctionDef) and n.name == "ask_decision_agent")
    calls = {getattr(n.func, "id", ""): n.lineno for n in ast.walk(ask) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)}
    assert calls["opportunity_system_prompt"] < calls["_log_decider_input"]


def test_stored_charter_is_moved_after_learned_text_without_duplication():
    stored = "Template\n\n" + OPPORTUNITY_CHARTER + "\n\nLearned memory"
    out = opportunity_system_prompt(stored)
    assert out.count(OPPORTUNITY_CHARTER) == 1
    assert out.index("Learned memory") < out.index(OPPORTUNITY_CHARTER)
    assert opportunity_system_prompt(out) == out


@pytest.mark.parametrize("source", ["Stored custom feedback template", "Code default feedback template"])
def test_every_feedback_api_path_appends_charter_after_identity_and_reasoning(source):
    method = _method("feedback_agent.py", "_build_feedback_api_params", {
        "get_agent_model": lambda agent: "stub-model",
        "append_reasoning_guidance": lambda prompt, *args: prompt + "\nREASONING",
        "opportunity_system_prompt": opportunity_system_prompt,
        "get_reasoning_token_cap": lambda *args: 4000,
        "get_model_token_params": lambda *args: {"max_tokens": 4000},
        "get_model_temperature_params": lambda *args: {},
        "get_reasoning_params": lambda *args: {}, "MODEL_TEMPERATURE": 1,
    })
    params = method(source, "analyze", "FeedbackAgent", 4000)
    assert params["messages"][0]["content"] == source + "\nREASONING\n\n" + OPPORTUNITY_CHARTER


@pytest.mark.parametrize("stored", [True, False])
def test_summarizer_feedback_bypass_is_guarded_for_custom_and_fallback_prompts(monkeypatch, stored):
    def active(agent):
        if not stored:
            raise LookupError("no prompt")
        return {"system_prompt": "Stored template", "user_prompt_template": "{content} {feedback_context}",
                "version": 7, "soul": "identity", "memory": "evidence"}
    monkeypatch.setitem(sys.modules, "prompt_manager", SimpleNamespace(get_active_prompt=active))
    calls = []
    method = _method("main.py", "get_openai_summary", {
        "json": json, "re": re, "SUMMARY_WITH_IMAGES_ONLY": True,
        "feedback_tracker": SimpleNamespace(get_latest_feedback=lambda: {"summarizer_feedback": json.dumps(REGIME)}),
        "prompt_manager": SimpleNamespace(ask_openai=lambda *args, **kw: calls.append((args, kw))),
    })
    method("source", "<p>news</p>", [])
    (args, kwargs), = calls
    assert "withheld" in args[1] and args[1].endswith(OPPORTUNITY_CHARTER)
    assert REGIME not in args[0] and REGIME not in args[1]
    assert kwargs["agent_name"] == "SummarizerAgent"
