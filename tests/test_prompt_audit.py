"""Operator audits are scoped, previewed, immutable and transactionally activated.

The database exists only in this fixture. The real activation callback is loaded
without importing config, so these tests cannot touch the trader or local DB.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, text

from policy_graph import prompt_audit as audit
from policy_graph.model import AGENT_PREFIX, FIELDS
from policy_safety import PolicyOpportunityError

CFG = "reviewed-config"
OTHER = "unrelated-config"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def activate():
    """Use production transition/event logic, with its config import excluded."""
    names = {"_canonical_agent_type", "_current_active_version",
             "_record_activation_event", "set_active_prompt_version"}
    source = ast.parse((ROOT / "prompt_manager.py").read_text())
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    namespace = {"text": text, "uuid": uuid}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "prompt_manager.py", "exec"), namespace)
    return namespace["set_active_prompt_version"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT NOT NULL,
            agent_type TEXT NOT NULL, version INTEGER NOT NULL,
            system_prompt TEXT, user_prompt_template TEXT, strategy_directives TEXT,
            soul TEXT, memory TEXT, description TEXT, created_by TEXT,
            is_active BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        conn.execute(text("""CREATE TABLE decider_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT NOT NULL,
            content TEXT, kind TEXT, tags TEXT, ticker TEXT, source TEXT, weight REAL,
            active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        conn.execute(text("""CREATE TABLE prompt_activation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            batch_id TEXT NOT NULL, config_hash TEXT NOT NULL, agent_type TEXT NOT NULL,
            from_version INTEGER, to_version INTEGER, action TEXT NOT NULL, actor TEXT, reason TEXT)"""))
        conn.execute(text(audit.DDL))
        for cfg in (CFG, OTHER):
            for agent in AGENT_PREFIX:
                for version, active in ((2, True), (7, False)):
                    conn.execute(text("""INSERT INTO prompt_versions
                        (config_hash,agent_type,version,system_prompt,user_prompt_template,
                         strategy_directives,soul,memory,description,created_by,is_active)
                        VALUES (:cfg,:agent,:version,:system,:user,:directives,:soul,:memory,
                                'Original source','fixture',:active)"""), {
                        "cfg": cfg, "agent": agent, "version": version, "active": active,
                        "system": "System {strategy_directives}. Literal {{escaped}}.",
                        "user": "Analyze {content}. JSON example {\"answer\": \"ok\"}.",
                        "directives": f"Original {agent} strategy. Use supplied price and event facts.",
                        "soul": f"Original {agent} identity.", "memory": "Original durable observation.",
                    })
            for content, active in (("IF FOMC is within 1 session THEN SELL confirmed Holdings.", True),
                                    ("An older inactive lesson must remain intact.", False)):
                conn.execute(text("""INSERT INTO decider_memory
                    (config_hash,content,kind,tags,ticker,source,weight,active)
                    VALUES (:cfg,:content,'rule','[\"event\"]','GOOG','feedback',1.5,:active)"""),
                    {"cfg": cfg, "content": content, "active": active})
    yield engine
    engine.dispose()


def rows(engine, table, cfg=None):
    with engine.connect() as conn:
        query = f"SELECT * FROM {table}"
        if cfg is not None:
            query += " WHERE config_hash=:cfg"
        return [dict(row) for row in conn.execute(text(query + " ORDER BY id" if table != "agent_prompt_audits"
                                                     else query + " ORDER BY batch_id"), {"cfg": cfg}).mappings()]


def state(engine):
    return {table: rows(engine, table) for table in (
        "prompt_versions", "decider_memory", "prompt_activation_events", "agent_prompt_audits")}


def spec_for(engine, cfg=CFG):
    current = [row for row in rows(engine, "prompt_versions", cfg) if row["is_active"]]
    memory = next(row for row in rows(engine, "decider_memory", cfg) if row["active"])
    return {
        "agents": {row["agent_type"]: {
            "from_version": row["version"], "source_row_id": row["id"],
            "description": "Reviewed readability and evidence correction",
            "classification": ["wording", "reviewed behavior"],
            "fields": {field: row[field] + "\nReviewed explanation." for field in FIELDS},
        } for row in current},
        "memory_actions": {
            "retire_ids": [memory["id"]],
            "insert": [{"kind": "lesson", "tags": ["evidence", "reviewed"], "weight": 1.25,
                        "content": "A macro date alone does not determine a position exit. Apply its approved conditions."}],
        },
    }


def apply_review(engine, activate, spec, *, preview=None, cfg=CFG):
    plan = preview or audit.preview(engine, cfg, spec=spec)
    return audit.apply(engine, cfg, activate, spec=spec,
                       expected_source_hash=plan["source_hash"], expected_spec_hash=plan["spec_hash"])


def test_preview_fingerprints_source_and_spec_without_writing(db):
    spec = spec_for(db)
    before = state(db)
    plan = audit.preview(db, CFG, spec=spec)
    assert state(db) == before
    assert plan["applied"] is False and len(plan["source_hash"]) == len(plan["spec_hash"]) == 64
    assert plan == audit.preview(db, CFG, spec=deepcopy(spec))
    assert {change["agent_type"] for change in plan["agents"]} == set(AGENT_PREFIX)
    assert all(set(change["changed_fields"]) == set(FIELDS) for change in plan["agents"])
    assert all(change["characters_after"] > change["characters_before"] for change in plan["agents"])
    assert all(change["diff"]["memory"][0] == "--- memory:before" for change in plan["agents"])
    assert plan["retire_memory_ids"] == spec["memory_actions"]["retire_ids"]
    assert plan["new_memory_count"] == 1


def test_apply_uses_audited_callback_one_batch_and_preserves_original_rows(db, activate):
    spec = spec_for(db)
    plan = audit.preview(db, CFG, spec=spec)
    before = state(db)
    result = apply_review(db, activate, spec, preview=plan)
    assert result["applied"] is True and len(result["policies"]) == 4
    # The version allocator includes inactive history rather than reusing v3.
    assert all(item["before_version"] == 2 and item["after_version"] == 8 for item in result["policies"])
    all_prompts = {row["id"]: row for row in rows(db, "prompt_versions")}
    for old in before["prompt_versions"]:
        expected = {**old, "is_active": 0} if old["config_hash"] == CFG and old["is_active"] else old
        assert all_prompts[old["id"]] == expected
    for transition in result["policies"]:
        new = all_prompts[transition["after_id"]]
        assert new["is_active"] and new["created_by"] == audit.ACTOR and new["config_hash"] == CFG
        assert {field: new[field] for field in FIELDS} == spec["agents"][new["agent_type"]]["fields"]
    events = rows(db, "prompt_activation_events", CFG)
    assert len(events) == 4 and {row["batch_id"] for row in events} == {result["batch_id"]}
    assert all(row["action"] == audit.ACTION and row["actor"] == audit.ACTOR for row in events)
    assert all((row["from_version"], row["to_version"]) == (2, 8) for row in events)
    memory_before = {row["id"]: row for row in before["decider_memory"]}
    memories = rows(db, "decider_memory", CFG)
    retired_id = spec["memory_actions"]["retire_ids"][0]
    retired = next(row for row in memories if row["id"] == retired_id)
    assert not retired["active"]
    assert {k: v for k, v in retired.items() if k not in ("active", "updated_at")} == {
        k: v for k, v in memory_before[retired_id].items() if k not in ("active", "updated_at")}
    new_memory = next(row for row in memories if row["id"] not in memory_before)
    assert new_memory["active"] and new_memory["source"] == "operator_audit" and new_memory["ticker"] is None
    assert json.loads(new_memory["tags"]) == ["evidence", "reviewed"] and new_memory["weight"] == 1.25
    assert new_memory["content"] == spec["memory_actions"]["insert"][0]["content"]
    journal_rows = rows(db, "agent_prompt_audits", CFG)
    assert len(journal_rows) == 1
    journal = journal_rows[0]
    assert journal["batch_id"] == result["batch_id"] and journal["source_hash"] == plan["source_hash"]
    payload = json.loads(journal["journal_json"])
    assert payload["spec_hash"] == plan["spec_hash"] and payload["policies"] == result["policies"]
    assert payload["memories"][0]["content"] == memory_before[retired_id]["content"]
    assert payload["memories"][0]["before_active"] is True and payload["memories"][0]["after_active"] is False
    assert rows(db, "prompt_versions", OTHER) == [r for r in before["prompt_versions"] if r["config_hash"] == OTHER]
    assert rows(db, "decider_memory", OTHER) == [r for r in before["decider_memory"] if r["config_hash"] == OTHER]


@pytest.mark.parametrize("change", ["missing_agent", "extra_agent", "version", "row_id", "placeholder", "nontext"])
def test_plan_requires_all_four_reviewed_agents_matching_versions_and_placeholders(db, change):
    spec = spec_for(db)
    item = spec["agents"]["DeciderAgent"]
    if change == "missing_agent":
        del spec["agents"]["FeedbackAgent"]
    elif change == "extra_agent":
        spec["agents"]["UnknownAgent"] = deepcopy(item)
    elif change == "version":
        item["from_version"] += 1
    elif change == "row_id":
        item["source_row_id"] += 100
    elif change == "placeholder":
        item["fields"]["user_prompt_template"] = item["fields"]["user_prompt_template"].replace("{content}", "{context}")
    else:
        item["fields"]["soul"] = ["not plain text"]
    before = state(db)
    with pytest.raises(audit.AuditConflict):
        audit.preview(db, CFG, spec=spec)
    assert state(db) == before


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_snapshot_requires_exactly_one_active_prompt_for_each_agent(db, mutation):
    spec = spec_for(db)
    with db.begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET is_active=:active WHERE config_hash=:h AND agent_type='DeciderAgent' AND version=:version"),
                     {"active": mutation == "duplicate", "h": CFG, "version": 7 if mutation == "duplicate" else 2})
    with pytest.raises(audit.AuditConflict, match="exactly one active"):
        audit.preview(db, CFG, spec=spec)


def test_explicit_config_never_falls_back_to_unrelated_active_rows(db):
    with pytest.raises(audit.AuditConflict, match="exactly one active"):
        audit.preview(db, "missing-config", spec=spec_for(db))
    with pytest.raises(audit.AuditConflict, match="source version changed"):
        audit.preview(db, OTHER, spec=spec_for(db, CFG))


def test_unrelated_config_changes_do_not_stale_the_review(db, activate):
    spec = spec_for(db)
    plan = audit.preview(db, CFG, spec=spec)
    with db.begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET memory='Unrelated update' WHERE config_hash=:h"), {"h": OTHER})
        conn.execute(text("UPDATE decider_memory SET content='Unrelated observation' WHERE config_hash=:h"), {"h": OTHER})
    assert audit.preview(db, CFG, spec=spec)["source_hash"] == plan["source_hash"]
    result = apply_review(db, activate, spec, preview=plan)
    assert result["applied"]
    assert all(row["memory"] == "Unrelated update" for row in rows(db, "prompt_versions", OTHER))


@pytest.mark.parametrize("target", ["active_prompt", "active_memory", "inactive_memory", "new_memory"])
def test_concurrent_source_modification_rejects_without_losing_external_change(db, activate, target):
    spec = spec_for(db)
    plan = audit.preview(db, CFG, spec=spec)
    with db.begin() as conn:
        if target == "active_prompt":
            conn.execute(text("UPDATE prompt_versions SET memory='Concurrent edit' WHERE config_hash=:h AND is_active=TRUE"), {"h": CFG})
        elif target == "new_memory":
            conn.execute(text("INSERT INTO decider_memory(config_hash,content,active) VALUES (:h,'Concurrent new memory',TRUE)"), {"h": CFG})
        else:
            conn.execute(text("UPDATE decider_memory SET content='Concurrent edit' WHERE config_hash=:h AND active=:active"),
                         {"h": CFG, "active": target == "active_memory"})
    concurrent = state(db)
    with pytest.raises(audit.AuditConflict, match="changed after the audit preview"):
        apply_review(db, activate, spec, preview=plan)
    assert state(db) == concurrent


def test_changed_proposal_requires_new_review_even_with_unchanged_source(db, activate):
    spec = spec_for(db)
    plan = audit.preview(db, CFG, spec=spec)
    spec["agents"]["DeciderAgent"]["fields"]["memory"] += " A different proposal."
    before = state(db)
    with pytest.raises(audit.AuditConflict, match="Proposed audit changed"):
        apply_review(db, activate, spec, preview=plan)
    assert state(db) == before


def test_callback_failure_rolls_back_inserted_versions_and_activation_events(db, activate):
    spec = spec_for(db)
    before = state(db)
    calls = []
    def fail_after_second_transition(*args, **kwargs):
        result = activate(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            raise RuntimeError("Activation callback failed")
        return result
    with pytest.raises(RuntimeError, match="Activation callback failed"):
        apply_review(db, fail_after_second_transition, spec)
    assert len(calls) == 2 and state(db) == before


def test_unsafe_new_memory_rolls_back_all_policy_and_retirement_changes(db, activate):
    spec = spec_for(db)
    spec["memory_actions"]["insert"].append({"content": "IF INDEX REGIME is RISK-OFF THEN pass."})
    # This error occurs after real audited callbacks and after memory retirement.
    before = state(db)
    calls = []
    def capture(*args, **kwargs):
        calls.append(activate(*args, **kwargs))
    with pytest.raises(PolicyOpportunityError, match="opportunity charter"):
        apply_review(db, capture, spec)
    assert len(calls) == 4 and state(db) == before


def test_a_memory_retirement_cannot_select_another_configs_row(db):
    spec = spec_for(db)
    spec["memory_actions"]["retire_ids"] = [next(row["id"] for row in rows(db, "decider_memory", OTHER) if row["active"])]
    with pytest.raises(audit.AuditConflict, match="no longer active"):
        audit.preview(db, CFG, spec=spec)


def test_apply_requires_audited_callback(db):
    spec = spec_for(db)
    with pytest.raises(ValueError, match="activation callback"):
        apply_review(db, None, spec)
