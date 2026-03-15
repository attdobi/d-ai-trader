"""Smoke test: dashboard decider import paths remain valid."""

import importlib
import sys
import types

import pytest


@pytest.fixture
def dashboard_server_module(monkeypatch):
    """Import dashboard_server with deterministic stub dependencies."""

    flask_stub = types.ModuleType("flask")

    class _DummyFlaskApp:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def route(self, *args, **kwargs):
            def _decorator(func):
                self.routes.append((args, kwargs, func.__name__))
                return func

            return _decorator

    flask_stub.Flask = _DummyFlaskApp
    flask_stub.render_template = lambda *args, **kwargs: {"template": args[0] if args else None}
    flask_stub.jsonify = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    flask_stub.request = types.SimpleNamespace(args={}, json=None, method="GET")
    monkeypatch.setitem(sys.modules, "flask", flask_stub)

    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.text = lambda sql: sql
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_stub)

    sqlalchemy_exc_stub = types.ModuleType("sqlalchemy.exc")

    class _IntegrityError(Exception):
        pass

    sqlalchemy_exc_stub.IntegrityError = _IntegrityError
    monkeypatch.setitem(sys.modules, "sqlalchemy.exc", sqlalchemy_exc_stub)

    config_stub = types.ModuleType("config")
    config_stub.engine = object()
    config_stub.get_gpt_model = lambda: "gpt-test"
    config_stub.get_prompt_version_config = lambda *_args, **_kwargs: {}
    config_stub.get_trading_mode = lambda: "simulation"
    config_stub.get_current_config_hash = lambda: "test-config-hash"
    config_stub.set_gpt_model = lambda *_args, **_kwargs: None
    config_stub.SCHWAB_ACCOUNT_HASH = "acct-hash"
    config_stub.IS_MARGIN_ACCOUNT = False
    monkeypatch.setitem(sys.modules, "config", config_stub)

    init_prompts_stub = types.ModuleType("initialize_prompts")
    init_prompts_stub.DEFAULT_PROMPTS = {
        "FeedbackAgent": {
            "system_prompt": "stub",
            "user_prompt_template": "stub",
            "description": "stub",
        }
    }
    monkeypatch.setitem(sys.modules, "initialize_prompts", init_prompts_stub)

    prompt_manager_stub = types.ModuleType("prompt_manager")
    prompt_manager_stub.initialize_config_prompts = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "prompt_manager", prompt_manager_stub)

    decider_stub = types.ModuleType("decider_agent")

    def _extract_companies_from_summaries(*_args, **_kwargs):
        return []

    def _build_momentum_recap(*_args, **_kwargs):
        return "momentum"

    def _fetch_holdings(*_args, **_kwargs):
        return []

    def _store_momentum_snapshot(*_args, **_kwargs):
        return None

    decider_stub.extract_companies_from_summaries = _extract_companies_from_summaries
    decider_stub.build_momentum_recap = _build_momentum_recap
    decider_stub.fetch_holdings = _fetch_holdings
    decider_stub.store_momentum_snapshot = _store_momentum_snapshot
    decider_stub.SUMMARY_MAX_CHARS = 7777
    monkeypatch.setitem(sys.modules, "decider_agent", decider_stub)

    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))
    monkeypatch.setitem(sys.modules, "yfinance", types.ModuleType("yfinance"))

    feedback_stub = types.ModuleType("feedback_agent")

    class _DummyTradeOutcomeTracker:
        pass

    feedback_stub.TradeOutcomeTracker = _DummyTradeOutcomeTracker
    monkeypatch.setitem(sys.modules, "feedback_agent", feedback_stub)

    schwab_client_stub = types.ModuleType("schwab_client")
    schwab_client_stub.schwab_client = object()
    monkeypatch.setitem(sys.modules, "schwab_client", schwab_client_stub)

    update_prices_stub = types.ModuleType("update_prices")
    update_prices_stub.get_current_price_robust = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "update_prices", update_prices_stub)

    orchestrator_stub = types.ModuleType("d_ai_trader")

    class _DummyOrchestrator:
        pass

    orchestrator_stub.DAITraderOrchestrator = _DummyOrchestrator
    orchestrator_stub.mark_manual_decider_window = lambda: None
    monkeypatch.setitem(sys.modules, "d_ai_trader", orchestrator_stub)

    trading_interface_stub = types.ModuleType("trading_interface")
    trading_interface_stub.trading_interface = object()
    monkeypatch.setitem(sys.modules, "trading_interface", trading_interface_stub)

    sys.modules.pop("dashboard_server", None)
    module = importlib.import_module("dashboard_server")
    return module, decider_stub


def test_dashboard_decider_import_bindings(dashboard_server_module):
    module, decider_stub = dashboard_server_module

    assert module.extract_companies_from_summaries is decider_stub.extract_companies_from_summaries
    assert module.build_momentum_recap is decider_stub.build_momentum_recap
    assert module.fetch_holdings is decider_stub.fetch_holdings
    assert module.store_momentum_snapshot is decider_stub.store_momentum_snapshot
    assert module.SUMMARY_MAX_CHARS == 7777
