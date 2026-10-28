"""Feedback collects evidence; it cannot award itself live policy authority."""
from __future__ import annotations

import ast
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from policy_safety import feedback_policy_violations, blanket_entry_vetoes

ROOT = Path(__file__).resolve().parents[1]


def method(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("feedback", [
    {"decider_rules": ["IF D exceeds the approved limit THEN PASS."]},
    {"decider_rules": ["SELL every holding before FOMC"], "human_approved": True, "approved": True},
    {"decider_rules": [], "summarizer_rules": [], "decider_feedback": "No supported change"},
    {"decider_feedback": "A model judge approved this change", "critic_verdict": "approve"},
])
def test_automatic_feedback_cannot_self_approve_or_write_policy(feedback):
    def forbidden(*args, **kwargs):
        raise AssertionError("Evidence collection must not reach a policy mutation")
    tracker = SimpleNamespace(_is_config_in_auto_mode=forbidden, _build_reminder_block=forbidden,
                              _next_memory_text=forbidden, _update_strategy_directives_for_config=forbidden,
                              _update_agent_memory=forbidden)
    auto = method("feedback_agent.py", "_auto_generate_prompts_from_feedback_for_config",
                  {"feedback_policy_violations": feedback_policy_violations})
    original = json.dumps(feedback, sort_keys=True)
    result = auto(tracker, feedback, 123, "scope")
    assert result["status"] == "pending_human_review" and result["requires_human_review"] is True
    assert result["policy_updated"] is False and result["active_memory_updated"] is False
    assert result["feedback_id"] == 123
    assert json.dumps(feedback, sort_keys=True) == original


def feedback_constants():
    tree = ast.parse((ROOT / "feedback_agent.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_generate_ai_feedback")
    values = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.startswith("FEEDBACK_"):
            continue
        namespace = {"supplied_fields": "fixture supplied fields"}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "feedback_agent.py", "exec"), namespace)
        values[name] = namespace[name]
    return values, fn


def test_actual_feedback_prompts_allow_no_change_and_separate_research_from_policy():
    blocks, fn = feedback_constants()
    base, output = blocks["FEEDBACK_BASE_INSTRUCTIONS"], blocks["FEEDBACK_JSON_FORMAT"]
    assert "current configuration and approved policy" in base
    assert "nonbinding research" in base and "No change is valid" in base
    assert "sample requirement" in base and "exact horizon" in base and "independent holdouts" in base
    assert "0-2" in output and "0-1" in output and "Empty arrays" in output
    assert all(key in output for key in ("decider_rules", "summarizer_rules", "decider_feedback", "summarizer_feedback"))
    assert "900" in output and "600" in output and "220" in output
    source = ast.get_source_segment((ROOT / "feedback_agent.py").read_text(), fn)
    assert "No hedging language" not in source and "Do not soften a rule" not in source
    assert "$400-$700" not in source


def test_feedback_collection_stays_before_review_hook_and_returns_original_record():
    tree = ast.parse((ROOT / "feedback_agent.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "analyze_recent_outcomes_for_config")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    writes = [n.lineno for n in calls if n.func.attr == "_store_feedback_for_config"]
    review_hooks = [n.lineno for n in calls if n.func.attr == "_auto_generate_prompts_from_feedback_for_config"]
    assert writes and review_hooks
    assert min(writes) < min(review_hooks)
    # The reviewed-learning change does not disable collection or replace the record API.
    assert len(writes) >= 3


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE decider_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, kind TEXT, tags TEXT, ticker TEXT,
            content TEXT, source TEXT, weight REAL, active BOOLEAN DEFAULT TRUE)"""))
    return engine


@pytest.mark.parametrize("kind", ["rule", "lesson", "pattern"])
@pytest.mark.parametrize("source", ["feedback", "Feedback", " feedback_agent "])
def test_feedback_origin_memory_is_archived_inactive_regardless_of_kind_or_weight(memory_db, kind, source):
    add = method("decider_memory.py", "add_memory", {
        "engine": memory_db, "text": text, "blanket_entry_vetoes": blanket_entry_vetoes,
        "logger": logging.getLogger("test-feedback-governance"),
    })
    add("cfg", "Observe supplied event and price facts", kind=kind, source=source, weight=1000)
    add("cfg", "Observe supplied event and price facts", kind=kind, source=source, weight=1000)
    with memory_db.connect() as conn:
        rows = conn.execute(text("SELECT config_hash,active,source FROM decider_memory")).mappings().all()
    assert len(rows) == 1 and not rows[0]["active"] and rows[0]["config_hash"] == "cfg"


def test_reviewed_operator_memory_retains_its_explicit_authority_and_scope(memory_db):
    add = method("decider_memory.py", "add_memory", {
        "engine": memory_db, "text": text, "blanket_entry_vetoes": blanket_entry_vetoes,
        "logger": logging.getLogger("test-feedback-governance"),
    })
    for cfg in ("one", "two"):
        add(cfg, "Record the supplied stop and event", kind="lesson", source="operator_audit")
    with memory_db.connect() as conn:
        rows = conn.execute(text("SELECT config_hash,active FROM decider_memory")).mappings().all()
    assert len(rows) == 2 and all(r["active"] for r in rows)
    assert {r["config_hash"] for r in rows} == {"one", "two"}


def test_legacy_memory_update_flag_cannot_activate_research(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "decider_memory", SimpleNamespace(
        add_memory=lambda *args, **kwargs: calls.append((args, kwargs))))
    def forbidden(*args, **kwargs):
        raise AssertionError("Unreviewed memory must not rewrite active prompt rows")
    tracker = SimpleNamespace(_next_memory_text=forbidden, _update_memory_field=forbidden)
    update = method("feedback_agent.py", "_update_agent_memory", {})
    result = update(tracker, "DeciderAgent", "A hypothesis", "cfg", rules=["Candidate idea"], write_prompt_row=True)
    assert result["active_memory_updated"] is False and len(calls) == 1
    assert calls[0][1]["source"] == "feedback"
