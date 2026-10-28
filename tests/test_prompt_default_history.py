"""Published defaults seed fresh configs; existing prompt versions are history.

Only fixture SQLite is opened. Production functions are extracted without any
config import at module load, model call, market-data request or broker access.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from policy_graph import seed
from policy_graph.model import AGENT_PREFIX, FIELDS

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {agent: {**{field: f"Current release {agent} {field}" for field in FIELDS},
                    "description": f"Current release {agent}"} for agent in AGENT_PREFIX}


def load_functions(path, names, namespace):
    source = ast.parse((ROOT / path).read_text())
    selected = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    namespace.update(text=text, Path=Path, __file__=str(ROOT / path))
    exec(compile(ast.Module(body=selected, type_ignores=[]), path, "exec"), namespace)
    return namespace


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent_type TEXT, version INTEGER,
            config_hash TEXT, system_prompt TEXT, user_prompt_template TEXT,
            strategy_directives TEXT, soul TEXT, memory TEXT, description TEXT,
            created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT FALSE)"""))
        # The reset helper must not rewrite these legacy stores as a side effect.
        for table in ("ai_agent_prompts", "unified_prompts"):
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, content TEXT)"))
            conn.execute(text(f"INSERT INTO {table} VALUES (1,'Unchanged legacy history')"))
    yield engine
    engine.dispose()


def insert(engine, agent="DeciderAgent", cfg="existing", version=0, active=True, suffix="Historical"):
    with engine.begin() as conn:
        return conn.execute(text("""INSERT INTO prompt_versions
            (agent_type,version,config_hash,is_active,system_prompt,user_prompt_template,
             strategy_directives,soul,memory,description,created_by)
            VALUES (:agent,:version,:cfg,:active,:system_prompt,:user_prompt_template,
                    :strategy_directives,:soul,:memory,:description,'original_operator') RETURNING id"""), {
            "agent": agent, "version": version, "cfg": cfg, "active": active,
            **{field: f"{suffix} {field}" for field in FIELDS}, "description": f"{suffix} description",
        }).scalar_one()


def rows(engine, table="prompt_versions"):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]


def stub_sources(monkeypatch, engine, mode="default"):
    config = ModuleType("config")
    config.engine = engine
    config.env_first = lambda key, default=None: mode if key == "DAI_POLICY_SEED" else default
    config.get_current_config_hash = lambda: "existing"
    monkeypatch.setitem(sys.modules, "config", config)
    defaults = ModuleType("initialize_prompts")
    defaults.DEFAULT_PROMPTS = {**deepcopy(DEFAULTS), "feedback_analyzer": deepcopy(DEFAULTS["FeedbackAgent"])}
    monkeypatch.setitem(sys.modules, "initialize_prompts", defaults)


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("cfg", ["global", "existing"])
def test_startup_preserves_every_existing_baseline_byte_and_activation(db, active, cfg):
    for agent in AGENT_PREFIX:
        insert(db, agent, cfg, active=active)
    before = rows(db)
    namespace = load_functions("init_database.py", ["seed_v0_prompts", "_any_prompt_version_exists"], {
        "_normalized_prompt_rows": lambda: deepcopy(DEFAULTS), "_policy_seed_mode": lambda: "default",
        "InitStats": object,
    })
    stats = SimpleNamespace(seeded_prompts=0, updated_prompts=0, skipped_prompts=0)
    with db.begin() as conn:
        namespace["seed_v0_prompts"](conn, stats, cfg)
    assert rows(db) == before and stats.seeded_prompts == stats.updated_prompts == 0
    assert stats.skipped_prompts == 4


def test_startup_seeds_current_release_only_into_empty_config(db):
    for agent in AGENT_PREFIX:
        insert(db, agent, "global", suffix="Old global baseline")
    before = rows(db)
    namespace = load_functions("init_database.py", ["seed_v0_prompts", "_any_prompt_version_exists"], {
        "_normalized_prompt_rows": lambda: deepcopy(DEFAULTS), "_policy_seed_mode": lambda: "default",
        "InitStats": object,
    })
    stats = SimpleNamespace(seeded_prompts=0, updated_prompts=0, skipped_prompts=0)
    with db.begin() as conn:
        namespace["seed_v0_prompts"](conn, stats, "fresh")
    current = rows(db)
    assert current[:len(before)] == before and stats.seeded_prompts == 4
    fresh = [row for row in current if row["config_hash"] == "fresh"]
    assert {row["agent_type"] for row in fresh} == set(AGENT_PREFIX)
    for row in fresh:
        assert row["version"] == 0 and row["is_active"]
        assert all(row[field] == DEFAULTS[row["agent_type"]][field] for field in FIELDS)


def test_fresh_config_initializer_uses_current_defaults_not_stale_global(db, monkeypatch):
    stub_sources(monkeypatch, db)
    for agent in AGENT_PREFIX:
        insert(db, agent, "global", suffix="Stale global")
    before = rows(db)
    initialize = load_functions("prompt_manager.py", ["initialize_config_prompts"], {"engine": db})["initialize_config_prompts"]
    assert initialize("fresh") is True
    current = rows(db)
    assert current[:len(before)] == before
    fresh = [row for row in current if row["config_hash"] == "fresh"]
    assert len(fresh) == 4 and all(row["created_by"] == "init_database" and row["version"] == 0 for row in fresh)
    for row in fresh:
        assert all(row[field] == DEFAULTS[row["agent_type"]][field] for field in FIELDS)
    complete = rows(db)
    assert initialize("fresh") is False and rows(db) == complete


def test_fresh_config_initializer_preserves_latest_seed_provenance(db, monkeypatch):
    stub_sources(monkeypatch, db, mode="latest")
    latest = {agent: {field: f"Shipped latest {agent} {field}" for field in FIELDS} for agent in AGENT_PREFIX}
    monkeypatch.setattr(seed, "latest_fields", lambda root, agent: (
        latest[agent], {"version": 11, "config_hash": "shipped-source"}))
    initialize = load_functions("prompt_manager.py", ["initialize_config_prompts"], {"engine": db})["initialize_config_prompts"]
    assert initialize("fresh-latest")
    for row in rows(db):
        assert row["created_by"] == seed.CREATED_BY_LATEST
        assert "v11" in row["description"] and "shipped-source" in row["description"]
        assert all(row[field] == latest[row["agent_type"]][field] for field in FIELDS)


def test_initializer_does_not_fill_or_mutate_a_partly_initialized_config(db, monkeypatch):
    stub_sources(monkeypatch, db)
    insert(db, "CompanyExtractionAgent", active=False)
    before = rows(db)
    initialize = load_functions("prompt_manager.py", ["initialize_config_prompts"], {"engine": db})["initialize_config_prompts"]
    assert initialize("existing") is False and rows(db) == before


@pytest.mark.parametrize("cfg", ["existing", "global", None])
def test_reset_preserves_baseline_row_id_contents_timestamps_and_legacy_history(db, cfg):
    original = insert(db, cfg=cfg, active=False)
    insert(db, cfg="another-config")
    before = rows(db)
    legacy = {table: rows(db, table) for table in ("ai_agent_prompts", "unified_prompts")}
    ensure = load_functions("dashboard_server.py", ["_ensure_v0_prompt"], {})["_ensure_v0_prompt"]
    with db.begin() as conn:
        result = ensure(conn, "DeciderAgent", cfg or "global", DEFAULTS["DeciderAgent"])
    assert result == original and rows(db) == before
    assert all(rows(db, table) == values for table, values in legacy.items())


def test_reset_creates_only_missing_inactive_baseline_for_audited_activation(db):
    insert(db, cfg="existing", version=9)
    before = rows(db)
    ensure = load_functions("dashboard_server.py", ["_ensure_v0_prompt"], {})["_ensure_v0_prompt"]
    with db.begin() as conn:
        new_id = ensure(conn, "DeciderAgent", "existing", DEFAULTS["DeciderAgent"])
        assert ensure(conn, "feedback_analyzer", "existing", DEFAULTS["FeedbackAgent"]) is None
    current = rows(db)
    assert current[:len(before)] == before
    new = next(row for row in current if row["id"] == new_id)
    assert new["version"] == 0 and not new["is_active"]
    assert all(new[field] == DEFAULTS["DeciderAgent"][field] for field in FIELDS)


def test_save_after_reset_appends_and_cannot_overwrite_historical_v1(db, monkeypatch):
    stub_sources(monkeypatch, db)
    insert(db, version=0, active=True)
    insert(db, version=1, active=False, suffix="Audited prior version")
    insert(db, version=4, active=False)
    insert(db, cfg="unrelated", version=100)
    before = rows(db)
    events = []
    def activate(conn, agent, cfg, version, **metadata):
        events.append((agent, cfg, version, metadata))
        conn.execute(text("UPDATE prompt_versions SET is_active=FALSE WHERE config_hash=:cfg AND agent_type=:agent"),
                     {"cfg": cfg, "agent": agent})
        conn.execute(text("UPDATE prompt_versions SET is_active=TRUE WHERE config_hash=:cfg AND agent_type=:agent AND version=:version"),
                     {"cfg": cfg, "agent": agent, "version": version})
    save = load_functions("prompt_manager.py", ["create_new_prompt_version", "_canonical_agent_type"], {
        "engine": db, "set_active_prompt_version": activate,
        "refresh_latest_policy_graph": lambda *args, **kwargs: None,
    })["create_new_prompt_version"]
    new_id = save("DeciderAgent", "New system", "New user", "Reviewed save", created_by="operator",
                  strategy_directives="New directives", soul="New identity", memory="New observation")
    current = rows(db)
    assert events[0][:3] == ("DeciderAgent", "existing", 5)
    assert events[0][3] == {"action": "save", "actor": "operator", "reason": "Reviewed save"}
    for old in before:
        expected = {**old, "is_active": 0} if old["config_hash"] == "existing" and old["is_active"] else old
        assert next(row for row in current if row["id"] == old["id"]) == expected
    new = next(row for row in current if row["id"] == new_id)
    assert new["is_active"] and new["version"] == 5 and new["system_prompt"] == "New system"
