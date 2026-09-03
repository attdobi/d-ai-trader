"""`agents/<dir>/policy-graph/latest/` — the git-tracked copy of the ACTIVE version: written when
the active row is materialized, self-contained (overlays copied), byte-stable (volatile manifest
keys scrubbed), replaced when activation moves, untouched by reads of inactive versions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from policy_graph import service, store
from policy_graph.compile import compile_stored, read_version_dir
from policy_graph.model import InheritedText

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_pg_service_tests_latest", HERE / "test_policy_graph_service.py")
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
CFG = _svc.CFG


@pytest.fixture
def env(tmp_path, monkeypatch):
    # the same seeded SQLite database the service tests use
    from sqlalchemy import create_engine
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _svc.DDL:
            conn.execute(text(ddl))
        for agent, rows in (("DeciderAgent", _svc.DECIDER_ROWS), ("FeedbackAgent", _svc.FEEDBACK_ROWS)):
            for v, sd, soul, mem, by, active, at, rid in rows:
                conn.execute(text("""
                    INSERT INTO prompt_versions (id, agent_type, version, system_prompt, user_prompt_template,
                        strategy_directives, soul, memory, description, created_by, is_active, config_hash, created_at)
                    VALUES (:id, :a, :v, :sp, :up, :sd, :soul, :mem, :d, :by, :active, :h, :at)
                """), {"id": rid, "a": agent, "v": v, "sp": _svc.SYS21 if agent == "DeciderAgent" else "feedback sys",
                       "up": _svc.USER21 if agent == "DeciderAgent" else "feedback user", "sd": sd, "soul": soul,
                       "mem": mem, "d": f"{agent} v{v}", "by": by, "active": active, "h": CFG, "at": at})
        for rid, at, kind, tags, ticker, content, source, weight, active in _svc.MEMORY_ROWS:
            conn.execute(text("""
                INSERT INTO decider_memory (id, config_hash, created_at, updated_at, kind, tags, ticker, content,
                    source, weight, active) VALUES (:id, :h, :at, :at, :k, :tags, :tk, :c, :s, :w, :active)
            """), {"id": rid, "h": CFG, "at": at, "k": kind, "tags": tags, "tk": ticker, "c": content, "s": source,
                   "w": weight, "active": active})
    text_ = _svc.fx("decider_v18_soul.md")
    monkeypatch.setattr(service.inherited, "resolve_inherited",
                        lambda repo_root, agent_dir, filename, created_at, *, is_active_row: (
                            InheritedText(text=text_, source_path="x", git_sha="54a50e5e", resolution="worktree")
                            if filename == "SOUL.md" else None))
    yield {"engine": engine, "root": tmp_path, "common": {"repo_root": tmp_path, "is_margin_account": False}}
    engine.dispose()


def _latest(env, agent="decider"):
    return env["root"] / "agents" / agent / "policy-graph" / "latest"


def test_active_version_is_copied_to_latest(env):
    res = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert res["latest"] == "synced"
    lp = _latest(env)
    names = sorted(p.name for p in lp.iterdir())
    assert names == ["LATEST.json", "_code", "_ltm", "v21"]
    stamp = json.loads((lp / "LATEST.json").read_text())
    assert stamp["version"] == 21 and stamp["config_hash"] == CFG and stamp["prompt_version_id"] == 599
    v = read_version_dir(lp / "v21")                       # self-contained: overlays resolve inside latest/
    row = service.load_row(env["engine"], CFG, "DeciderAgent", 21)
    assert all((compile_stored(v)[f] or "") == (row[f] or "") for f in service.FIELDS)
    assert any(n.owner == "code" for n in v.nodes.values()) and any(n.owner == "decider_memory" for n in v.nodes.values())
    for m in lp.rglob("manifest.json"):
        data = json.loads(m.read_text())
        assert "materialized_at" not in data and "pid" not in data and "extracted_at" not in data
    # second materialize of the same row: nothing rewritten
    assert service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])["latest"] == "unchanged"


def test_inactive_versions_do_not_touch_latest(env):
    res = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 20, **env["common"])
    assert res["latest"] is None
    assert not _latest(env).exists()


def test_latest_follows_activation(env):
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    with env["engine"].begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET is_active = 0 WHERE config_hash = :h AND agent_type = 'DeciderAgent'"), {"h": CFG})
        conn.execute(text("UPDATE prompt_versions SET is_active = 1 WHERE config_hash = :h AND agent_type = 'DeciderAgent' AND version = 20"), {"h": CFG})
    res = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 20, **env["common"])
    assert res["latest"] == "synced"
    names = sorted(p.name for p in _latest(env).iterdir())
    assert "v20" in names and "v21" not in names
    assert json.loads((_latest(env) / "LATEST.json").read_text())["version"] == 20


def test_sync_latest_without_source_dir(tmp_path):
    assert store.sync_latest(tmp_path, "DeciderAgent", CFG, 99) is None
