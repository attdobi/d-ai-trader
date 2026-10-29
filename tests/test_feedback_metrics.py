"""Dashboard denominators, exact rolling windows and missing evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text, event

import feedback_metrics as metrics
from tests.test_dashboard_imports import dashboard_server_module, isolated_cash_flows, isolated_policy_graph  # noqa: F401

NOW = datetime(2026, 10, 29, 21, 34, 10, tzinfo=timezone.utc)


@pytest.fixture
def ledger():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE trade_outcomes (
            id INTEGER PRIMARY KEY, config_hash TEXT, ticker TEXT, sell_timestamp TIMESTAMP,
            gain_loss_percentage FLOAT, gain_loss_amount FLOAT, original_reason TEXT)"""))
    yield engine
    engine.dispose()


def insert(engine, ident, when, pct, *, cfg="active", ticker="ABC", amount=1, reason=None):
    if isinstance(when, datetime):
        when = metrics.utc_instant(when).replace(tzinfo=None)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO trade_outcomes VALUES
            (:id,:cfg,:ticker,:stamp,:pct,:amount,:reason)"""),
            {"id": ident, "cfg": cfg, "ticker": ticker, "stamp": when,
             "pct": pct, "amount": amount, "reason": reason})


def test_two_wins_today_and_previous_week_losses_make_seven_day_rate_valid(ledger):
    insert(ledger, 1, NOW-timedelta(hours=3), .03032698, ticker="DKNG", amount=14.569992)
    insert(ledger, 2, NOW-timedelta(hours=6), .02813560, ticker="PYPL", amount=11.029998)
    insert(ledger, 3, NOW-timedelta(days=7, hours=6), -.0407, ticker="DDOG", amount=-22.33)
    insert(ledger, 4, NOW-timedelta(days=7, hours=8), -.0197, ticker="AFRM", amount=-7.3185)
    insert(ledger, 5, NOW-timedelta(days=1), -.8, cfg="other")
    result = metrics.dashboard_period_metrics(ledger, "active", [7, 14], as_of=NOW)
    week, fortnight = result["7d"], result["14d"]
    assert week["total_trades"] == week["wins"] == 2
    assert week["success_rate"] == 1
    assert week["avg_profit"] == pytest.approx(.02923129)
    assert week["net_gain_dollars"] == pytest.approx(25.59999)
    assert fortnight["total_trades"] == 4 and fortnight["success_rate"] == .5
    assert week["window"]["start"] == "2026-10-22T21:34:10Z"
    assert week["window"]["end"] == fortnight["window"]["end"] == "2026-10-29T21:34:10Z"
    assert week["counting_unit"] == "closed_outcome_row"


def test_exact_lower_and_upper_bounds_are_inclusive_and_future_outcomes_excluded(ledger):
    insert(ledger, 1, NOW-timedelta(days=7), -.02)
    insert(ledger, 2, NOW, .04)
    insert(ledger, 3, NOW-timedelta(days=7, microseconds=1), .8)
    insert(ledger, 4, NOW+timedelta(microseconds=1), -.8)
    week = metrics.dashboard_period_metrics(ledger, "active", [7], as_of=NOW)["7d"]
    assert week["total_trades"] == 2 and week["success_rate"] == .5
    assert week["avg_profit"] == pytest.approx(.01)
    assert week["first_close_at"] == "2026-10-22T21:34:10Z"
    assert week["last_close_at"] == "2026-10-29T21:34:10Z"


def test_no_closed_outcomes_is_unknown_not_zero_performance(ledger):
    week = metrics.dashboard_period_metrics(ledger, "active", [7], as_of=NOW)["7d"]
    assert week["total_trades"] == week["wins"] == week["losses"] == week["flat_trades"] == 0
    assert week["success_rate"] is None and week["avg_profit"] is None
    assert week["first_close_at"] is None and week["net_gain_dollars"] is None


def test_invalid_returns_and_placeholders_do_not_become_losses_or_break_even(ledger):
    insert(ledger, 1, NOW, None)
    insert(ledger, 2, NOW, float("inf"))
    insert(ledger, 3, NOW, 0, amount=None)
    insert(ledger, 4, NOW, .2, ticker=" N/A ")
    insert(ledger, 5, NOW, .2, reason="MARKET IS CLOSED - no fill")
    week = metrics.dashboard_period_metrics(ledger, "active", [7], as_of=NOW)["7d"]
    assert week["closed_outcome_rows"] == 3 and week["unscored_trades"] == 2
    assert week["total_trades"] == week["flat_trades"] == 1
    assert week["success_rate"] == 0 and week["avg_profit"] == 0
    assert week["net_gain_dollars"] is None


def test_distinct_lot_rows_keep_equal_weight_and_dollar_break_even_category_is_not_win_rule(ledger):
    insert(ledger, 1, NOW, .01, amount=1)
    insert(ledger, 2, NOW, .01, amount=1)
    insert(ledger, 3, NOW, -.09, amount=-900)
    week = metrics.dashboard_period_metrics(ledger, "active", [7], as_of=NOW)["7d"]
    assert week["total_trades"] == 3 and week["wins"] == 2
    assert week["success_rate"] == pytest.approx(2/3)
    assert week["avg_profit"] == pytest.approx(-.07/3)
    assert week["net_gain_dollars"] == -898


def test_one_read_supplies_nested_windows_and_normalizes_aware_asof(ledger):
    insert(ledger, 1, NOW, .01)
    statements = []
    event.listen(ledger, "before_cursor_execute", lambda _c, _u, statement, *_a: statements.append(statement))
    result = metrics.dashboard_period_metrics(ledger, "active", [7, 14, 30, 90],
        as_of=datetime(2026, 10, 29, 14, 34, 10, tzinfo=timezone(timedelta(hours=-7))))
    assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")
    assert all(row["window"]["end"] == "2026-10-29T21:34:10Z" for row in result.values())
    assert all(row["total_trades"] == 1 for row in result.values())


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf"), "bad", True])
def test_invalid_numbers_remain_unknown(value):
    assert metrics.finite_number(value) is None


def test_bad_timestamps_are_not_assumed_to_have_closed_now():
    common = {"ticker": "ABC", "gain_loss_percentage": .1}
    row = metrics.summarize_closures([{**common, "sell_timestamp": None},
        {**common, "sell_timestamp": "bad"}], start=NOW-timedelta(days=7), end=NOW, days=7)
    assert row["total_trades"] == 0 and row["success_rate"] is None


def test_feedback_api_returns_metrics_without_latest_review_or_schema_mutation(dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    calls = []
    class ReadTracker:
        def __init__(self):
            raise AssertionError("A GET must not initialize tables")
        def get_latest_feedback(self):
            return None
    monkeypatch.setattr(dashboard, "TradeOutcomeTracker", ReadTracker)
    monkeypatch.setattr(dashboard, "get_current_config_hash", lambda: "active")
    monkeypatch.setattr(metrics, "utc_instant", lambda value=None: NOW)
    monkeypatch.setattr(metrics, "dashboard_period_metrics", lambda eng, cfg, periods, **kwargs:
        calls.append((eng, cfg, periods, kwargs)) or {"7d": {"total_trades": 0, "success_rate": None}})
    monkeypatch.setattr(dashboard.request, "args", {"periods": "7,14,30,7"})
    result = dashboard.get_feedback_data()["args"][0]
    assert result["status"] == "success" and result["latest_feedback"] is None
    assert result["as_of"] == "2026-10-29T21:34:10Z"
    assert result["period_analysis"]["7d"]["success_rate"] is None
    assert len(calls) == 1 and calls[0][1:] == ("active", [7, 14, 30], {"as_of": NOW})


def test_feedback_api_error_does_not_expose_database_diagnostics(dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    def broken(*_args, **_kwargs):
        raise RuntimeError("private database diagnostics")
    monkeypatch.setattr(metrics, "dashboard_period_metrics", broken)
    response, status = dashboard.get_feedback_data()
    assert status == 500
    assert response["args"][0] == {"status": "error", "error": "Feedback metrics are unavailable"}
