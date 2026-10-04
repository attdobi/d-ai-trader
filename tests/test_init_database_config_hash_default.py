"""init_database drops the legacy DEFAULT 'default' on config_hash (holdings, summaries,
trade_decisions) — the job archive/scripts/fix_constraints_only.py was written for but never ran.

Idempotent, Postgres only (skipped on SQLite), data untouched, and a failure on one table is logged
without aborting the init transaction."""
from __future__ import annotations

import ast
import importlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def init_db(monkeypatch):
    config_stub = types.ModuleType("config")
    config_stub.engine = None
    config_stub.get_current_config_hash = lambda: "cfg_test"
    monkeypatch.setitem(sys.modules, "config", config_stub)
    sys.modules.pop("init_database", None)
    module = importlib.import_module("init_database")
    yield module
    sys.modules.pop("init_database", None)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakePgConn:
    """Postgres-shaped connection: answers the information_schema probe from `defaults`,
    records ALTERs (and applies them), optionally fails the ALTER on one table."""

    def __init__(self, defaults, fail_on=None):
        self.dialect = types.SimpleNamespace(name="postgresql")
        self.defaults = dict(defaults)
        self.fail_on = fail_on
        self.alters = []
        self.savepoints = 0

    @contextmanager
    def begin_nested(self):
        self.savepoints += 1
        yield

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT column_default"):
            return _Result(self.defaults.get(params["table_name"]))
        if sql.startswith("ALTER TABLE"):
            table = sql.split()[2]
            if table == self.fail_on:
                raise RuntimeError("lock timeout")
            self.alters.append(sql)
            self.defaults[table] = None
            return _Result(None)
        raise AssertionError(f"unexpected SQL: {sql}")


def test_drops_only_the_literal_default_and_is_idempotent(init_db, capsys):
    conn = FakePgConn({"holdings": "'default'::text", "summaries": None, "trade_decisions": "'abc'::text"})
    assert init_db.drop_legacy_config_hash_defaults(conn) == ["holdings"]
    assert conn.alters == ["ALTER TABLE holdings ALTER COLUMN config_hash DROP DEFAULT"]
    assert conn.savepoints == 3
    assert "Dropped legacy 'default' column default: holdings.config_hash" in capsys.readouterr().out
    # second start: nothing left to drop
    assert init_db.drop_legacy_config_hash_defaults(conn) == []
    assert len(conn.alters) == 1


def test_covers_the_three_tables_fix_constraints_only_targeted(init_db):
    assert init_db.LEGACY_CONFIG_HASH_DEFAULT_TABLES == ("holdings", "summaries", "trade_decisions")
    conn = FakePgConn({t: "'default'::text" for t in init_db.LEGACY_CONFIG_HASH_DEFAULT_TABLES})
    assert init_db.drop_legacy_config_hash_defaults(conn) == ["holdings", "summaries", "trade_decisions"]


def test_a_failing_table_is_logged_and_the_rest_still_run(init_db, capsys):
    conn = FakePgConn({t: "'default'::text" for t in ("holdings", "summaries", "trade_decisions")},
                      fail_on="summaries")
    assert init_db.drop_legacy_config_hash_defaults(conn) == ["holdings", "trade_decisions"]
    assert "Could not drop the 'default' column default on summaries.config_hash: lock timeout" in capsys.readouterr().out


def test_sqlite_is_skipped(init_db):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        assert init_db.drop_legacy_config_hash_defaults(conn) == []
    engine.dispose()


def test_initialize_database_runs_the_migration_and_the_old_script_is_archived():
    tree = ast.parse((REPO_ROOT / "init_database.py").read_text(encoding="utf-8"))
    init = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "initialize_database")
    called = {n.func.id for n in ast.walk(init) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "drop_legacy_config_hash_defaults" in called
    assert not (REPO_ROOT / "fix_constraints_only.py").exists()
    assert (REPO_ROOT / "archive" / "scripts" / "fix_constraints_only.py").exists()
    assert "fix_constraints_only.py" not in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
