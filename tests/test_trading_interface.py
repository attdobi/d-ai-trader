"""Simulation-mode safety-net tests for TradingInterface.

These tests are fixture-only and avoid real API/database usage by stubbing imports.
"""

import importlib
import sys
import types

import pytest


@pytest.fixture
def trading_interface_module(monkeypatch):
    """Import trading_interface with deterministic lightweight stubs."""

    config_stub = types.ModuleType("config")
    config_stub.engine = object()
    config_stub.TRADING_MODE = "simulation"
    config_stub.DEBUG_TRADING = False
    config_stub.get_current_config_hash = lambda: "test-config-hash"
    config_stub.SCHWAB_ACCOUNT_HASH = "acct-hash"
    config_stub.IS_MARGIN_ACCOUNT = False
    monkeypatch.setitem(sys.modules, "config", config_stub)

    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.text = lambda sql: sql
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_stub)

    schwab_client_stub = types.ModuleType("schwab_client")

    class _DummySchwabClient:
        def authenticate(self):
            return False

    schwab_client_stub.schwab_client = _DummySchwabClient()
    schwab_client_stub.get_portfolio_snapshot = lambda: {}
    monkeypatch.setitem(sys.modules, "schwab_client", schwab_client_stub)

    schwab_ledger_stub = types.ModuleType("schwab_ledger")
    schwab_ledger_stub.compute_effective_funds = lambda funds: funds
    schwab_ledger_stub.components = lambda: {}
    monkeypatch.setitem(sys.modules, "schwab_ledger", schwab_ledger_stub)

    feedback_stub = types.ModuleType("feedback_agent")

    class _DummyTradeOutcomeTracker:
        pass

    feedback_stub.TradeOutcomeTracker = _DummyTradeOutcomeTracker
    monkeypatch.setitem(sys.modules, "feedback_agent", feedback_stub)

    safety_stub = types.ModuleType("safety_checks")

    class _DummySafetyManager:
        def validate_trade_decision(self, *args, **kwargs):
            return True, "ok"

        def check_portfolio_health(self, *args, **kwargs):
            return True, []

    safety_stub.safety_manager = _DummySafetyManager()
    monkeypatch.setitem(sys.modules, "safety_checks", safety_stub)

    update_calls = []
    decider_stub = types.ModuleType("decider_agent")

    def _update_holdings(decisions, skip_live_execution=False, run_id=None):
        update_calls.append(
            {
                "decisions": decisions,
                "skip_live_execution": skip_live_execution,
                "run_id": run_id,
            }
        )

    decider_stub.update_holdings = _update_holdings
    monkeypatch.setitem(sys.modules, "decider_agent", decider_stub)

    sys.modules.pop("trading_interface", None)
    module = importlib.import_module("trading_interface")
    return module, update_calls


def _make_interface(module, *, trading_mode="simulation", schwab_enabled=False, readonly_mode=False):
    interface = module.TradingInterface.__new__(module.TradingInterface)
    interface.trading_mode = trading_mode
    interface.schwab_enabled = schwab_enabled
    interface.readonly_mode = readonly_mode
    interface.live_view_only = False
    interface.feedback_tracker = None
    return interface


def test_execute_simulation_trades_forwards_to_update_holdings(trading_interface_module):
    module, update_calls = trading_interface_module
    interface = _make_interface(module, trading_mode="simulation")

    decisions = [
        {"action": "buy", "ticker": "NVDA", "amount_usd": 1200.0, "reason": "signal"},
        {"action": "sell", "ticker": "AAPL", "amount_usd": 900.0, "reason": "risk"},
    ]

    results = interface._execute_simulation_trades(decisions, run_id="run-123")

    assert len(update_calls) == 1, "Expected simulation path to call update_holdings exactly once"
    assert update_calls[0]["decisions"] == decisions
    assert update_calls[0]["run_id"] == "run-123"
    assert update_calls[0]["skip_live_execution"] is False

    assert [row["status"] for row in results] == ["executed", "executed"]
    assert [row["execution_type"] for row in results] == ["simulation", "simulation"]


def test_execute_simulation_trades_empty_decisions_returns_empty(trading_interface_module):
    module, update_calls = trading_interface_module
    interface = _make_interface(module, trading_mode="simulation")

    results = interface._execute_simulation_trades([], run_id="run-empty")

    assert results == []
    assert not update_calls, "No holdings update should happen when there are no decisions"


def test_execute_trade_decisions_simulation_mode_tallies_results(trading_interface_module):
    module, _ = trading_interface_module
    interface = _make_interface(module, trading_mode="simulation", schwab_enabled=True)

    interface._execute_simulation_trades = lambda decisions, run_id=None, skip_live_override=None: [
        {"status": "executed", "execution_type": "simulation"},
        {"status": "skipped", "execution_type": "simulation"},
        {"status": "error", "execution_type": "simulation", "error": "synthetic"},
    ]

    interface._run_safety_checks = lambda decisions: pytest.fail("Safety checks should not run in simulation mode")
    interface._execute_live_trades = lambda decisions: pytest.fail("Live execution should not run in simulation mode")

    decisions = [{"action": "buy", "ticker": "MSFT", "amount_usd": 1000.0, "reason": "signal"}]
    results = interface.execute_trade_decisions(decisions, run_id="run-summary")

    assert results["summary"]["total_decisions"] == 1
    assert results["summary"]["simulation_executed"] == 1
    assert results["summary"]["skipped"] == 1
    assert results["summary"]["errors"] == 1
    assert results["summary"]["live_executed"] == 0
    assert results["live_results"] == []
