"""`agents/<dir>/policy-graph/latest/` follows activation for EVERY agent, not just the Decider.

The Decider re-materializes its active version each cycle, so its latest/ was current; the Summarizer
sat at v24 while latest/ still held v22, because nothing else materialized an activated version. Now:

  * policy_graph.service.sync_active_latest materializes each agent's active version (per-agent
    failures are reported, never raised);
  * prompt_manager.refresh_latest_policy_graph wraps it with the trader's repo root / margin flag and
    never raises;
  * every activation writer calls it AFTER its transaction commits (never inside it), and the weekly
    feedback job and trader startup run it for all agents as a safety net.
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from policy_graph import service
from tests.test_policy_graph_latest import CFG, _latest, env  # noqa: F401 — the seeded SQLite fixture

REPO_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- service.sync_active_latest


def test_sync_active_latest_materializes_every_active_agent(env):
    res = service.sync_active_latest(env["engine"], CFG, **env["common"])
    assert res == {"DeciderAgent": "synced", "SummarizerAgent": None, "FeedbackAgent": "synced",
                   "CompanyExtractionAgent": None}
    assert json.loads((_latest(env, "feedback") / "LATEST.json").read_text())["version"] == 8
    assert json.loads((_latest(env) / "LATEST.json").read_text())["version"] == 21
    again = service.sync_active_latest(env["engine"], CFG, agent_types=["FeedbackAgent"], **env["common"])
    assert again == {"FeedbackAgent": "unchanged"}


def test_sync_active_latest_follows_an_activation(env):
    service.sync_active_latest(env["engine"], CFG, agent_types=["FeedbackAgent"], **env["common"])
    with env["engine"].begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET is_active = 0 WHERE config_hash = :h AND agent_type = 'FeedbackAgent'"), {"h": CFG})
        conn.execute(text("UPDATE prompt_versions SET is_active = 1 WHERE config_hash = :h AND agent_type = 'FeedbackAgent' AND version = 7"), {"h": CFG})
    res = service.sync_active_latest(env["engine"], CFG, agent_types=["FeedbackAgent"], **env["common"])
    assert res == {"FeedbackAgent": "synced"}
    names = sorted(p.name for p in _latest(env, "feedback").iterdir())
    assert "v7" in names and "v8" not in names


def test_sync_active_latest_reports_one_failure_and_keeps_going(env, monkeypatch):
    real = service._ensure

    def _flaky(ctx, agent_type, row, **kw):
        if agent_type == "DeciderAgent":
            raise RuntimeError("disk full")
        return real(ctx, agent_type, row, **kw)

    monkeypatch.setattr(service, "_ensure", _flaky)
    res = service.sync_active_latest(env["engine"], CFG, agent_types=["DeciderAgent", "FeedbackAgent", "Nope"],
                                     **env["common"])
    assert res["DeciderAgent"] == "error: RuntimeError: disk full"
    assert res["FeedbackAgent"] == "synced"
    assert res["Nope"].startswith("error: BadRequest")


# ----------------------------------------------------------------------------- prompt_manager wrapper + writers


@pytest.fixture
def pm_file_env(monkeypatch, tmp_path):
    """prompt_manager bound to a FILE SQLite database, so a second connection only sees committed rows."""
    url = f"sqlite:///{tmp_path / 'pm.db'}"
    engine = create_engine(url)
    config_stub = types.ModuleType("config")
    config_stub.engine = engine
    config_stub.get_current_config_hash = lambda: "cfg_test"
    config_stub.IS_MARGIN_ACCOUNT = True
    monkeypatch.setitem(sys.modules, "config", config_stub)
    sys.modules.pop("prompt_manager", None)
    pm = importlib.import_module("prompt_manager")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, agent_type TEXT NOT NULL, version INTEGER NOT NULL,
                system_prompt TEXT, user_prompt_template TEXT, strategy_directives TEXT, soul TEXT DEFAULT '',
                memory TEXT DEFAULT '', description TEXT, created_by TEXT, is_active BOOLEAN DEFAULT 0,
                config_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """))
        conn.execute(text("""
            CREATE TABLE prompt_activation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                batch_id TEXT NOT NULL, config_hash TEXT NOT NULL, agent_type TEXT NOT NULL,
                from_version INTEGER, to_version INTEGER, action TEXT NOT NULL, actor TEXT, reason TEXT)
        """))
        conn.execute(text("""
            INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template, config_hash, is_active)
            VALUES ('SummarizerAgent', 3, 'sys', 'user', 'cfg_test', 1)
        """))
    yield pm, url
    sys.modules.pop("prompt_manager", None)
    engine.dispose()


def _committed_active(url, agent="SummarizerAgent"):
    other = create_engine(url)          # a separate connection: sees committed rows only
    try:
        with other.connect() as conn:
            row = conn.execute(text("SELECT version FROM prompt_versions WHERE agent_type = :a AND is_active = 1"),
                               {"a": agent}).fetchone()
        return row.version if row else None
    finally:
        other.dispose()


def test_refresh_wrapper_passes_trader_settings(pm_file_env, monkeypatch):
    pm, _url = pm_file_env
    calls = []

    def _fake(engine, config_hash, **kw):
        calls.append((engine, config_hash, kw))
        return {"FeedbackAgent": "synced"}

    monkeypatch.setattr(service, "sync_active_latest", _fake)
    assert pm.refresh_latest_policy_graph(None, ["feedback_analyzer"], materialized_by="save") == {"FeedbackAgent": "synced"}
    engine, cfg, kw = calls[-1]
    assert engine is pm.engine and cfg == "cfg_test"
    assert kw == {"repo_root": Path(pm.__file__).resolve().parent, "is_margin_account": True,
                  "agent_types": ["FeedbackAgent"], "materialized_by": "save"}
    pm.refresh_latest_policy_graph("other_cfg")
    assert calls[-1][1] == "other_cfg" and calls[-1][2]["agent_types"] is None
    # unknown agent types are dropped (deduplicated after canonicalizing); nothing known → no call
    pm.refresh_latest_policy_graph("cfg_test", ["feedback_analyzer", "MomentumAgent", "FeedbackAgent"])
    assert calls[-1][2]["agent_types"] == ["FeedbackAgent"]
    n = len(calls)
    assert pm.refresh_latest_policy_graph("cfg_test", ["MomentumAgent"]) == {}
    assert len(calls) == n


def test_refresh_wrapper_never_raises(pm_file_env, monkeypatch, capsys):
    pm, _url = pm_file_env

    def _boom(*_a, **_k):
        raise RuntimeError("store busy")

    monkeypatch.setattr(service, "sync_active_latest", _boom)
    assert pm.refresh_latest_policy_graph("cfg_test", ["SummarizerAgent"]) == {}
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "Policy graph latest/ refresh skipped: store busy" in out


def test_save_and_undo_refresh_latest_after_commit(pm_file_env, monkeypatch):
    pm, url = pm_file_env
    seen = []

    def _record(config_hash, agent_types=None, *, materialized_by="activation"):
        seen.append((config_hash, agent_types, materialized_by, _committed_active(url)))
        return {}

    monkeypatch.setattr(pm, "refresh_latest_policy_graph", _record)
    pm.create_new_prompt_version("SummarizerAgent", "sys2", "user2", "weekly save")
    # called once, after commit: a separate connection already sees v4 active
    assert seen == [("cfg_test", ["SummarizerAgent"], "save", 4)]

    result = pm.undo_last_prompt_activation("cfg_test", actor="dashboard")
    assert result["undone"] is True
    assert seen[-1] == ("cfg_test", ["SummarizerAgent"], "undo", 3)


def test_save_survives_a_failing_refresh(pm_file_env, monkeypatch):
    pm, url = pm_file_env
    monkeypatch.setattr(service, "sync_active_latest", lambda *a, **k: (_ for _ in ()).throw(OSError("ro fs")))
    prompt_id = pm.create_new_prompt_version("SummarizerAgent", "sys2", "user2", "weekly save")
    assert prompt_id and _committed_active(url) == 4


# ----------------------------------------------------------------------------- writers: call sites (AST contract)


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _calls(func, name):
    return [n for n in ast.walk(func) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def _inside_with(node, parents, stop):
    cur = parents.get(node)
    while cur is not None and cur is not stop:
        if isinstance(cur, (ast.With, ast.AsyncWith)):
            return True
        cur = parents.get(cur)
    return False


@pytest.mark.parametrize("path", ["dashboard_server.py", "prompt_manager.py"])
def test_every_activation_writer_refreshes_latest_outside_its_transaction(path):
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"), filename=path)
    parents = _parents(tree)
    writers = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
               and f.name not in ("set_active_prompt_version", "undo_last_prompt_activation")
               and _calls(f, "set_active_prompt_version")]
    assert writers, f"no activation writers found in {path}"
    for f in writers:
        refresh = [c for c in _calls(f, "refresh_latest_policy_graph") if not _inside_with(c, parents, f)]
        assert refresh, f"{path}:{f.name} activates a version but never refreshes latest/ after commit"


def test_orchestrator_syncs_latest_weekly_and_at_startup():
    tree = ast.parse((REPO_ROOT / "d_ai_trader.py").read_text(encoding="utf-8"))
    funcs = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
    assert _calls(funcs["scheduled_feedback_job"], "sync_policy_graph_latest")
    assert _calls(funcs["run"], "sync_policy_graph_latest")
    sync = funcs["sync_policy_graph_latest"]
    assert any(isinstance(n, ast.Try) for n in sync.body), "the sync must be wrapped in try/except"
    assert _calls(sync, "refresh_latest_policy_graph")
