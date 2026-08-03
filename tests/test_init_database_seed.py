"""Regression tests for idempotent v0 prompt seeding in init_database.

Every trader startup runs init_database.py (via start_d_ai_trader.sh). The
seeding step must never re-insert or re-activate a v0 baseline row once a
feedback-evolved higher version owns the active flag for the same
(agent_type, config_hash).
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _import_init_database(monkeypatch):
    """Import a fresh init_database with a stubbed config module (no DB)."""
    config_stub = types.ModuleType("config")
    config_stub.engine = None
    config_stub.get_current_config_hash = lambda: "cfg_test"
    monkeypatch.setitem(sys.modules, "config", config_stub)

    sys.modules.pop("init_database", None)
    return importlib.import_module("init_database")


class FakeResult:
    def __init__(self, row=None, rowcount=0):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class FakeConn:
    """Minimal stand-in for a SQLAlchemy connection.

    Routes the specific statements seed_v0_prompts / deactivate_superseded_v0_prompts
    issue and records everything executed for assertions.
    """

    def __init__(self, v0_rows=None, any_version=False, any_active=False, update_rowcount=0):
        self.v0_rows = v0_rows or {}
        self.any_version = any_version
        self.any_active = any_active
        self.update_rowcount = update_rowcount
        self.statements = []  # (kind, sql, params)

    def _classify(self, sql):
        flat = " ".join(sql.split()).lower()
        if flat.startswith("insert into prompt_versions"):
            return "insert"
        if flat.startswith("update prompt_versions"):
            return "update"
        if flat.startswith("select id,"):
            return "v0_lookup"
        if flat.startswith("select 1") and "is_active = true" in flat:
            return "active_lookup"
        if flat.startswith("select 1"):
            return "version_lookup"
        raise AssertionError(f"Unexpected SQL in seed path: {sql}")

    def execute(self, clause, params=None):
        sql = str(clause)
        kind = self._classify(sql)
        self.statements.append((kind, sql, params or {}))

        if kind == "v0_lookup":
            return FakeResult(row=self.v0_rows.get(params["agent_type"]))
        if kind == "version_lookup":
            return FakeResult(row=(1,) if self.any_version else None)
        if kind == "active_lookup":
            return FakeResult(row=(1,) if self.any_active else None)
        if kind == "update":
            return FakeResult(rowcount=self.update_rowcount)
        return FakeResult()

    def executed(self, kind):
        return [(sql, params) for k, sql, params in self.statements if k == kind]


def _canonical_payloads(init_db):
    rows = init_db._normalized_prompt_rows()
    return {agent: payload for agent, payload in rows.items() if agent != "feedback_analyzer"}


def _synced_row(payload, *, is_active, id_=101):
    """A DB row whose content already matches the committed baseline."""
    return types.SimpleNamespace(
        id=id_,
        system_prompt=payload["system_prompt"],
        user_prompt_template=payload["user_prompt_template"],
        strategy_directives=payload["strategy_directives"],
        description=payload["description"],
        is_active=is_active,
        soul=payload["soul"] or "committed-soul",
        memory=payload["memory"] or "committed-memory",
    )


def test_seeds_v0_into_empty_config(monkeypatch):
    init_db = _import_init_database(monkeypatch)
    payloads = _canonical_payloads(init_db)

    conn = FakeConn(v0_rows={}, any_version=False)
    stats = init_db.InitStats()
    init_db.seed_v0_prompts(conn, stats, "cfg_test")

    inserts = conn.executed("insert")
    assert len(inserts) == len(payloads)
    assert stats.seeded_prompts == len(payloads)
    assert stats.skipped_prompts == 0


def test_never_reinserts_v0_when_history_exists(monkeypatch):
    """Restart after a feedback promotion (v0 gone, v1+ present) must not resurrect v0."""
    init_db = _import_init_database(monkeypatch)
    payloads = _canonical_payloads(init_db)

    conn = FakeConn(v0_rows={}, any_version=True)
    stats = init_db.InitStats()
    init_db.seed_v0_prompts(conn, stats, "cfg_test")

    assert conn.executed("insert") == []
    assert conn.executed("update") == []
    assert stats.seeded_prompts == 0
    assert stats.skipped_prompts == len(payloads)


def test_dormant_v0_stays_inactive_when_higher_version_active(monkeypatch):
    """The historical bug: restarts re-activated v0 alongside the active v13."""
    init_db = _import_init_database(monkeypatch)
    payloads = _canonical_payloads(init_db)

    v0_rows = {agent: _synced_row(payload, is_active=False) for agent, payload in payloads.items()}
    conn = FakeConn(v0_rows=v0_rows, any_active=True)
    stats = init_db.InitStats()
    init_db.seed_v0_prompts(conn, stats, "cfg_test")

    assert conn.executed("update") == [], "in-sync dormant v0 must not be touched"
    assert stats.updated_prompts == 0
    assert stats.skipped_prompts == len(payloads)


def test_dormant_v0_reactivated_only_when_nothing_active(monkeypatch):
    init_db = _import_init_database(monkeypatch)
    payloads = _canonical_payloads(init_db)

    v0_rows = {agent: _synced_row(payload, is_active=False) for agent, payload in payloads.items()}
    conn = FakeConn(v0_rows=v0_rows, any_active=False)
    stats = init_db.InitStats()
    init_db.seed_v0_prompts(conn, stats, "cfg_test")

    updates = conn.executed("update")
    assert len(updates) == len(payloads)
    for sql, _params in updates:
        assert "is_active = TRUE" in sql
        assert "created_at" not in sql, "seeding must not rewrite created_at"


def test_content_sync_never_steals_active_flag(monkeypatch):
    """Baseline text drift is synced, but activation stays with the evolved version."""
    init_db = _import_init_database(monkeypatch)
    payloads = _canonical_payloads(init_db)

    v0_rows = {}
    for agent, payload in payloads.items():
        row = _synced_row(payload, is_active=False)
        row.system_prompt = "stale baseline text"
        v0_rows[agent] = row

    conn = FakeConn(v0_rows=v0_rows, any_active=True)
    stats = init_db.InitStats()
    init_db.seed_v0_prompts(conn, stats, "cfg_test")

    updates = conn.executed("update")
    assert len(updates) == len(payloads)
    for sql, _params in updates:
        assert "is_active" not in sql, "content sync must not re-activate v0"
        assert "created_at" not in sql


def test_deactivates_superseded_active_v0_rows(monkeypatch):
    init_db = _import_init_database(monkeypatch)

    conn = FakeConn(update_rowcount=2)
    stats = init_db.InitStats()
    init_db.deactivate_superseded_v0_prompts(conn, stats)

    updates = conn.executed("update")
    assert len(updates) == 1
    sql = updates[0][0]
    flat = " ".join(sql.split()).lower()
    assert "set is_active = false" in flat
    assert "version = 0" in flat
    assert "version > 0" in flat and "is_active = true" in flat, (
        "cleanup must only target v0 rows shadowed by an active higher version"
    )
    assert stats.deactivated_prompts == 2
