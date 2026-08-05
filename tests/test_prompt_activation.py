"""Tests for the centralized prompt activation switchboard.

All is_active flips on prompt_versions go through
prompt_manager.set_active_prompt_version, which records every transition in
prompt_activation_events (SQL) so changes are auditable and undoable.
Runs against an in-memory SQLite database.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest
from sqlalchemy import create_engine, text

CFG = "cfg_test"


@pytest.fixture
def pm_env(monkeypatch):
    """Fresh prompt_manager bound to an in-memory SQLite engine."""
    engine = create_engine("sqlite://")

    config_stub = types.ModuleType("config")
    config_stub.engine = engine
    config_stub.get_current_config_hash = lambda: CFG
    monkeypatch.setitem(sys.modules, "config", config_stub)

    sys.modules.pop("prompt_manager", None)
    pm = importlib.import_module("prompt_manager")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_type TEXT NOT NULL,
                version INTEGER NOT NULL,
                system_prompt TEXT,
                user_prompt_template TEXT,
                strategy_directives TEXT,
                soul TEXT DEFAULT '',
                memory TEXT DEFAULT '',
                description TEXT,
                created_by TEXT,
                is_active BOOLEAN DEFAULT 0,
                config_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE prompt_activation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                batch_id TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                from_version INTEGER,
                to_version INTEGER,
                action TEXT NOT NULL,
                actor TEXT,
                reason TEXT
            )
        """))

    yield pm, engine

    sys.modules.pop("prompt_manager", None)
    engine.dispose()


def _add_version(engine, agent, version, *, active=False, cfg=CFG):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO prompt_versions
                (agent_type, version, system_prompt, user_prompt_template, config_hash, is_active)
            VALUES (:agent, :version, 'sys', 'user', :cfg, :active)
        """), {"agent": agent, "version": version, "cfg": cfg, "active": active})


def _active_version(engine, agent, cfg=CFG):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT version FROM prompt_versions
            WHERE agent_type = :agent AND config_hash = :cfg AND is_active = 1
        """), {"agent": agent, "cfg": cfg}).fetchall()
    assert len(rows) <= 1, f"multiple active versions for {agent}: {rows}"
    return rows[0].version if rows else None


def _events(engine, cfg=CFG):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT batch_id, agent_type, from_version, to_version, action, actor
            FROM prompt_activation_events
            WHERE config_hash = :cfg
            ORDER BY id
        """), {"cfg": cfg}).fetchall()


def test_set_active_switches_version_and_records_event(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)
    _add_version(engine, "DeciderAgent", 13)

    with engine.begin() as conn:
        result = pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 13, action="save", actor="feedback_agent")

    assert result["changed"] is True
    assert result["from_version"] == 0
    assert result["to_version"] == 13
    assert _active_version(engine, "DeciderAgent") == 13

    events = _events(engine)
    assert len(events) == 1
    assert (events[0].from_version, events[0].to_version) == (0, 13)
    assert events[0].action == "save"
    assert events[0].actor == "feedback_agent"


def test_set_active_noop_when_target_already_active(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 13, active=True)

    with engine.begin() as conn:
        result = pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 13, action="reset_v0", actor="dashboard")

    assert result["changed"] is False
    assert _events(engine) == []


def test_set_active_noop_still_enforces_single_active(pm_env):
    """Polluted dual-active rows collapse to just the target version."""
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)
    _add_version(engine, "DeciderAgent", 13, active=True)

    with engine.begin() as conn:
        result = pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 13, action="save", actor="system")

    assert result["changed"] is False
    assert _active_version(engine, "DeciderAgent") == 13


def test_set_active_unknown_version_raises(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)

    with engine.begin() as conn:
        with pytest.raises(ValueError, match="v99 does not exist"):
            pm.set_active_prompt_version(
                conn, "DeciderAgent", CFG, 99, action="save", actor="system")

    assert _active_version(engine, "DeciderAgent") == 0


def test_set_active_is_config_scoped(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)
    _add_version(engine, "DeciderAgent", 13)
    _add_version(engine, "DeciderAgent", 0, active=True, cfg="other_cfg")

    with engine.begin() as conn:
        pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 13, action="save", actor="system")

    assert _active_version(engine, "DeciderAgent") == 13
    assert _active_version(engine, "DeciderAgent", cfg="other_cfg") == 0


def test_undo_restores_previous_versions_for_whole_batch(pm_env):
    """A reset batch covering several agents is undone as one unit."""
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0)
    _add_version(engine, "DeciderAgent", 13, active=True)
    _add_version(engine, "SummarizerAgent", 0)
    _add_version(engine, "SummarizerAgent", 10, active=True)

    batch = "reset-batch-1"
    with engine.begin() as conn:
        for agent in ("DeciderAgent", "SummarizerAgent"):
            pm.set_active_prompt_version(
                conn, agent, CFG, 0, action="reset_v0", actor="dashboard", batch_id=batch)

    assert _active_version(engine, "DeciderAgent") == 0
    assert _active_version(engine, "SummarizerAgent") == 0

    result = pm.undo_last_prompt_activation(CFG, actor="dashboard")

    assert result["undone"] is True
    assert result["undid_batch"] == batch
    assert result["undid_action"] == "reset_v0"
    assert _active_version(engine, "DeciderAgent") == 13
    assert _active_version(engine, "SummarizerAgent") == 10

    undo_events = [e for e in _events(engine) if e.action == "undo"]
    assert len(undo_events) == 2


def test_undo_twice_reapplies_the_change(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0)
    _add_version(engine, "DeciderAgent", 13, active=True)

    with engine.begin() as conn:
        pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 0, action="reset_v0", actor="dashboard")

    pm.undo_last_prompt_activation(CFG)
    assert _active_version(engine, "DeciderAgent") == 13

    pm.undo_last_prompt_activation(CFG)
    assert _active_version(engine, "DeciderAgent") == 0


def test_undo_with_no_history(pm_env):
    pm, engine = pm_env
    result = pm.undo_last_prompt_activation(CFG)
    assert result["undone"] is False


def test_undo_restores_nothing_active_state(pm_env):
    """If nothing was active before the change, undo returns to that state."""
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0)

    with engine.begin() as conn:
        pm.set_active_prompt_version(
            conn, "DeciderAgent", CFG, 0, action="reset_v0", actor="dashboard")
    assert _active_version(engine, "DeciderAgent") == 0

    result = pm.undo_last_prompt_activation(CFG)
    assert result["undone"] is True
    assert _active_version(engine, "DeciderAgent") is None


def test_history_returns_events_newest_first(pm_env):
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)
    _add_version(engine, "DeciderAgent", 1)
    _add_version(engine, "DeciderAgent", 2)

    with engine.begin() as conn:
        pm.set_active_prompt_version(conn, "DeciderAgent", CFG, 1, action="save", actor="a")
        pm.set_active_prompt_version(conn, "DeciderAgent", CFG, 2, action="save", actor="b")

    history = pm.get_prompt_activation_history(CFG)
    assert [h["to_version"] for h in history] == [2, 1]
    assert history[0]["from_version"] == 1


def test_create_new_prompt_version_records_activation_event(pm_env):
    """The feedback promotion path goes through the audited switchboard."""
    pm, engine = pm_env
    _add_version(engine, "DeciderAgent", 0, active=True)
    _add_version(engine, "DeciderAgent", 12, active=False)

    # Active v0 → the reuse-v1 path; from a higher active it appends MAX+1.
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE prompt_versions SET is_active = 1
            WHERE agent_type = 'DeciderAgent' AND version = 12
        """))
        conn.execute(text("""
            UPDATE prompt_versions SET is_active = 0
            WHERE agent_type = 'DeciderAgent' AND version = 0
        """))

    pm.create_new_prompt_version(
        agent_type="DeciderAgent",
        system_prompt="new sys",
        user_prompt_template="new user",
        description="evolved",
        created_by="feedback_agent",
    )

    assert _active_version(engine, "DeciderAgent") == 13
    events = _events(engine)
    assert len(events) == 1
    assert (events[0].from_version, events[0].to_version) == (12, 13)
    assert events[0].action == "save"
