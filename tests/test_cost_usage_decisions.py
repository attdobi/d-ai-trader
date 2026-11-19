"""Cost endpoint over real SQLite/Flask, without local config or model calls."""
from __future__ import annotations

import ast
import copy
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, inspect, text

from api_cost_usage import DECISIONS_AGENT
from policy_router.decisions_log import ensure_schema


CFG = "cost-test"
TODAY = datetime.now(ZoneInfo("America/Los_Angeles")).date()


@pytest.fixture
def env(monkeypatch):
    flask = pytest.importorskip("flask")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE api_usage (
                id INTEGER PRIMARY KEY, config_hash TEXT, ts TIMESTAMP,
                agent_type TEXT, model TEXT, prompt_tokens INTEGER,
                completion_tokens INTEGER, reasoning_tokens INTEGER,
                total_tokens INTEGER, cost_usd REAL)
        """))
        conn.execute(text("""
            INSERT INTO api_usage VALUES
                (1, :cfg, :day, 'SummarizerAgent', 'gpt-6-luna', 1000, 100, 20, 1100, 999)
        """), {"cfg": CFG, "day": TODAY.isoformat() + " 12:00:00"})
    calls = []
    def reprice(model, prompt, completion, **kwargs):
        calls.append((model, prompt, completion))
        from shared.chat_pricing import usage_cost
        return usage_cost(model, {
            "prompt_tokens": prompt, "completion_tokens": completion,
            "cached_input_tokens": kwargs.get("cached_input_tokens") or 0,
            "cache_write_tokens": kwargs.get("cache_write_tokens") or 0,
            "cache_retention": kwargs.get("cache_retention"),
        }, kwargs["pricing"])
    stub = types.ModuleType("config")
    stub.load_model_pricing = lambda: {"gpt-6-luna": {"input": .10, "output": .50}}
    stub.compute_api_cost = reprice
    monkeypatch.setitem(sys.modules, "config", stub)
    tree = ast.parse((Path(__file__).resolve().parents[1] / "dashboard_server.py").read_text())
    route = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                               and n.name == "get_cost_usage"))
    route.decorator_list = []
    namespace = {"engine": engine, "text": text, "jsonify": flask.jsonify,
                 "request": flask.request, "get_current_config_hash": lambda: CFG}
    exec(compile(ast.Module(body=[route], type_ignores=[]), "cost-route", "exec"), namespace)
    app = flask.Flask("cost-test")
    app.add_url_rule("/api/cost-usage", view_func=namespace["get_cost_usage"])
    yield {"engine": engine, "client": app.test_client(), "repriced": calls}
    engine.dispose()


def _comparison(env, *, cfg=CFG, day=TODAY, status="ok", attempted=True,
                prompt=1000, cached=400, writes=200, output=77, cost=.000069):
    ensure_schema(env["engine"])
    with env["engine"].begin() as conn:
        conn.execute(text("""
            INSERT INTO policy_router_comparisons (
                config_hash, run_id, decided_at, status, provider, model, request_attempted,
                input_tokens, cached_input_tokens, cache_write_tokens, output_tokens, cost_usd,
                nodes_json, comparison_json, pinned_json)
            VALUES (:cfg, 'run', :day, :status, 'openai_decisions', 'gpt-6-luna', :attempted,
                    :prompt, :cached, :writes, :output, :cost, '[]', '{}', '[]')
        """), {"cfg": cfg, "day": day.isoformat() + " 12:00:00", "status": status,
               "attempted": attempted, "prompt": prompt, "cached": cached,
               "writes": writes, "output": output, "cost": cost})


def _get(env, days=7):
    response = env["client"].get(f"/api/cost-usage?days={days}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _agent(data, name):
    return next(a for a in data["per_agent"] if a["agent"] == name)


def test_fresh_install_preserves_chat_repricing_and_does_not_create_router_table(env):
    data = _get(env)
    assert data["total_cost"] == pytest.approx(.00015)  # ignore stored Chat cost of 999
    assert data["today"]["calls"] == 1 and data["today"]["tokens"] == 1100
    assert data["decisions_usage_available"] is False
    assert data["cost_complete"] and data["usage_complete"]
    assert {a["agent"] for a in data["per_agent"]} == {
        "SummarizerAgent", "CompanyExtractionAgent", "DeciderAgent", "FeedbackAgent"}
    assert "policy_router_comparisons" not in inspect(env["engine"]).get_table_names()


def test_router_cache_writes_and_free_output_use_recorded_tariff_once(env):
    # 1000 total input includes 400 cached + 200 written. Correct price is
    # (400*.10 + 400*.01 + 200*.125)/1M = .000069, regardless of output.
    _comparison(env, output=99_999)
    _comparison(env, status="fallback", prompt=1000, cached=0, writes=0, output=0, cost=.0001)
    data = _get(env)
    router = _agent(data, DECISIONS_AGENT)
    assert router["calls"] == 2  # requests, not questions/nodes
    assert router["prompt_tokens"] == 2000
    assert router["cached_input_tokens"] == 400 and router["cache_write_tokens"] == 200
    assert router["completion_tokens"] == 99_999
    assert router["cost"] == pytest.approx(.000169)
    assert data["total_cost"] == pytest.approx(.000319)
    assert data["today"]["cost"] == pytest.approx(.000319)
    assert data["today"]["calls"] == 3 and data["today"]["tokens"] == 103099
    assert env["repriced"] == [("gpt-6-luna", 1000, 100)]
    assert data["cost_complete"] and data["usage_complete"]


def test_provider_totals_are_scoped_to_config_window_and_actual_attempts(env):
    _comparison(env, cfg="another-config", cost=50)
    _comparison(env, day=TODAY - timedelta(days=7), cost=60)
    _comparison(env, day=TODAY + timedelta(days=1), cost=70)
    _comparison(env, attempted=False, status="fallback", prompt=None, cached=None,
                writes=None, output=None, cost=None)
    _comparison(env, day=TODAY - timedelta(days=6), cost=.000069)
    data = _get(env)
    assert _agent(data, DECISIONS_AGENT)["calls"] == 1
    assert data["total_cost"] == pytest.approx(.000219)
    assert data["today"]["cost"] == pytest.approx(.00015)
    assert data["unknown_cost_calls"] == 0


def test_unknown_billing_is_null_with_known_subtotal_not_free(env):
    _comparison(env)
    _comparison(env, status="fallback", prompt=None, cached=None, writes=None,
                output=None, cost=None)
    data = _get(env)
    router = _agent(data, DECISIONS_AGENT)
    assert router["calls"] == 2 and router["cost"] is None
    assert router["known_cost"] == pytest.approx(.000069)
    assert router["unknown_cost_calls"] == router["unknown_token_calls"] == 1
    assert data["total_cost"] is None and data["today"]["cost"] is None
    assert data["known_total_cost"] == pytest.approx(.000219)
    assert data["today"]["known_cost"] == pytest.approx(.000219)
    assert not data["cost_complete"] and not data["usage_complete"]
    daily = next(r for r in data["daily"] if r["agent"] == DECISIONS_AGENT)
    assert daily["cost"] is None and daily["unknown_cost_calls"] == 1


def test_yesterdays_unknown_request_does_not_hide_todays_known_total(env):
    _comparison(env, day=TODAY - timedelta(days=1), status="fallback", prompt=None,
                cached=None, writes=None, output=None, cost=None)
    data = _get(env)
    assert data["total_cost"] is None
    assert data["today"]["cost"] == pytest.approx(.00015)
    assert data["today"]["unknown_cost_calls"] == 0


def test_chat_unknown_tariff_marks_window_incomplete(env):
    with env["engine"].begin() as conn:
        conn.execute(text("""INSERT INTO api_usage VALUES
            (2,:cfg,:day,'DeciderAgent','unpriced',1000,50,5,1050,NULL)"""),
            {"cfg":CFG, "day": TODAY.isoformat()})
    data = _get(env)
    assert data["known_total_cost"] == pytest.approx(.00015)
    assert data["unknown_cost_calls"] == 1 and data["total_cost"] is None
    assert _agent(data, "DeciderAgent")["cost"] is None


def test_chat_cache_reprices_and_uses_per_request_context_tier(env, monkeypatch):
    model = "gpt-6.2-sol"
    monkeypatch.setattr(sys.modules["config"], "load_model_pricing", lambda: {
        "gpt-6-luna": {"input": .1, "output": .5},
        model: {"input": 2, "output": 10, "cached_input": .1, "cache_write": 2.5,
                "long_input_threshold": 272000}})
    with env["engine"].begin() as conn:
        for col in ("cached_input_tokens INT", "cache_write_tokens INT", "cache_retention TEXT"):
            conn.execute(text(f"ALTER TABLE api_usage ADD COLUMN {col}"))
        for ident in (2, 3):
            conn.execute(text("""INSERT INTO api_usage VALUES
                (:id,:cfg,:day,'DeciderAgent',:m,200000,3000,1500,203000,NULL,100000,50000,'30m')"""),
                {"id": ident, "cfg":CFG, "day": TODAY.isoformat(), "m": model})
    data = _get(env)
    decider = _agent(data, "DeciderAgent")
    # Each call was below the long-context threshold.
    assert data["cost_complete"] and decider["cost"] == pytest.approx(2 * .265)
    assert decider["cached_input_tokens"] == 200_000 and decider["cache_write_tokens"] == 100_000


@pytest.mark.parametrize("days", [1, 7])
def test_inclusive_pacific_report_has_exactly_days_calendar_dates(env, days):
    start = TODAY - timedelta(days=days-1)
    for day in {start - timedelta(days=1), start, TODAY + timedelta(days=1)}:
        with env["engine"].begin() as conn:
            conn.execute(text("""INSERT INTO api_usage (config_hash,ts,agent_type,model,prompt_tokens,
                completion_tokens,reasoning_tokens,total_tokens) VALUES (:h,:d,'SummarizerAgent','gpt-6-luna',100,50,1,150)"""),
                {"h": CFG, "d": day.isoformat()+" 23:59:59"})
    data = _get(env, days)
    assert data["first_date"] == start.isoformat() and data["last_date"] == TODAY.isoformat()
    assert _agent(data, "SummarizerAgent")["calls"] == 2
    assert {r["day"] for r in data["daily"]} == {start.isoformat(), TODAY.isoformat()}
