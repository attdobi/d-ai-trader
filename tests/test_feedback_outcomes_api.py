"""Recent closure API: real SQL cohort filtering and honest display values."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

# Import with real dependencies before the dashboard fixture installs its stubs.
import feedback_metrics  # noqa: F401
from tests.test_dashboard_imports import dashboard_server_module, isolated_cash_flows, isolated_policy_graph  # noqa: F401

NOW = datetime(2026, 10, 29, 21, 34, 10)


@pytest.fixture(scope="module")
def outcomes_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE trade_outcomes (
            id INTEGER PRIMARY KEY, config_hash TEXT, ticker TEXT, sell_timestamp TIMESTAMP,
            purchase_price FLOAT, sell_price FLOAT, shares FLOAT, gain_loss_percentage FLOAT,
            gain_loss_amount FLOAT, outcome_category TEXT, hold_duration_days INTEGER,
            original_reason TEXT)"""))
    yield engine
    engine.dispose()


@pytest.fixture
def ledger(outcomes_db):
    with outcomes_db.begin() as conn:
        conn.execute(text("DELETE FROM trade_outcomes"))
    return outcomes_db


def insert(engine, ident, **overrides):
    row = {"id": ident, "config_hash": "active", "ticker": "ABC", "sell_timestamp": NOW,
           "purchase_price": 100, "sell_price": 103, "shares": 2, "gain_loss_percentage": .03,
           "gain_loss_amount": 6, "outcome_category": "moderate_profit", "hold_duration_days": 1,
           "original_reason": None}
    row.update(overrides)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO trade_outcomes VALUES
            (:id,:config_hash,:ticker,:sell_timestamp,:purchase_price,:sell_price,:shares,
             :gain_loss_percentage,:gain_loss_amount,:outcome_category,:hold_duration_days,
             :original_reason)"""), row)


class QueryAdapter:
    """Execute the dashboard's actual SQL against SQLite despite import stubs.

    The shared dashboard fixture replaces sqlalchemy.text with a string identity
    function. This adapter restores its execution wrapper only; filtering, dates,
    ordering and LIMIT remain the production query executed by SQLite.
    """
    def __init__(self, engine):
        self.engine = engine
        self.queries = []

    def connect(self):
        adapter = self
        class Connection:
            def __enter__(self):
                self.connection = adapter.engine.connect()
                return self
            def __exit__(self, *exc):
                self.connection.close()
            def execute(self, statement, params):
                adapter.queries.append((str(statement), dict(params)))
                return self.connection.execute(text(str(statement)), params)
        return Connection()


def configure_api(dashboard, monkeypatch, ledger):
    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return NOW
    adapter = QueryAdapter(ledger)
    monkeypatch.setattr(dashboard, "engine", adapter)
    monkeypatch.setattr(dashboard, "datetime", FrozenDateTime)
    monkeypatch.setattr(dashboard, "get_current_config_hash", lambda: "active")
    return adapter


def body(dashboard):
    response = dashboard.get_trade_outcomes()
    assert not isinstance(response, tuple), "Expected a successful recorded-outcome response"
    return response["args"][0]


def test_recent_outcomes_filter_scope_future_and_placeholders_with_actual_sql(ledger, dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    insert(ledger, 1, ticker="DKNG", original_reason=None)
    insert(ledger, 2, ticker="PYPL", sell_timestamp=NOW-timedelta(days=7))
    insert(ledger, 3, config_hash="another-config")
    insert(ledger, 4, sell_timestamp=NOW+timedelta(microseconds=1))
    insert(ledger, 5, ticker=" N/a ")
    insert(ledger, 6, ticker="  ")
    insert(ledger, 7, ticker=None)
    insert(ledger, 8, original_reason="MARKET IS CLOSED: no execution")
    adapter = configure_api(dashboard, monkeypatch, ledger)
    result = body(dashboard)
    assert [row["id"] for row in result] == [1, 2]
    assert result[0]["sell_date"] == "2026-10-29T21:34:10Z"
    assert result[1]["sell_date"] == "2026-10-22T21:34:10Z"
    assert all("original_reason" not in row and "config_hash" not in row for row in result)
    assert len(adapter.queries) == 1
    assert adapter.queries[0][1] == {"config_hash": "active", "as_of": NOW}


def test_unknown_numeric_values_stay_null_and_percent_fraction_converts_once(ledger, dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    insert(ledger, 1, ticker="UNKNOWN", purchase_price=None, sell_price=0, shares=None,
           gain_loss_amount=None, gain_loss_percentage=None, hold_duration_days=None,
           outcome_category=None)
    insert(ledger, 2, ticker="LOSS", gain_loss_percentage=-.0158, gain_loss_amount=-3.16)
    insert(ledger, 3, ticker="NONFINITE", purchase_price=float("inf"),
           sell_price=-float("inf"), shares=float("inf"),
           gain_loss_percentage=float("inf"), gain_loss_amount=-float("inf"))
    configure_api(dashboard, monkeypatch, ledger)
    result = {row["ticker"]: row for row in body(dashboard)}
    unknown = result["UNKNOWN"]
    assert unknown["purchase_price"] is unknown["shares"] is unknown["net_gain_dollars"] is None
    assert unknown["gain_loss_pct"] is unknown["hold_days"] is unknown["category"] is None
    assert unknown["sell_price"] == 0
    assert result["LOSS"]["gain_loss_pct"] == pytest.approx(-1.58)
    assert result["LOSS"]["net_gain_dollars"] == pytest.approx(-3.16)
    assert all(result["NONFINITE"][key] is None for key in
               ("purchase_price", "sell_price", "shares", "gain_loss_pct", "net_gain_dollars"))


def test_latest_fifty_are_deterministic_and_equal_timestamp_lots_remain_distinct(ledger, dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    for ident in range(1, 56):
        insert(ledger, ident, sell_timestamp=NOW-timedelta(minutes=ident))
    insert(ledger, 90, ticker="SAME-LOT")
    insert(ledger, 91, ticker="SAME-LOT")
    # These newer records cannot consume places in the visible fifty.
    insert(ledger, 100, ticker="N/A")
    insert(ledger, 101, config_hash="another-config")
    insert(ledger, 102, sell_timestamp=NOW+timedelta(days=1))
    configure_api(dashboard, monkeypatch, ledger)
    first = body(dashboard)
    second = body(dashboard)
    assert first == second
    assert len(first) == 50
    assert [row["id"] for row in first] == [91, 90, *range(1, 49)]
    assert [row["ticker"] for row in first[:2]] == ["SAME-LOT", "SAME-LOT"]


def test_empty_cohort_is_an_empty_list(ledger, dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    configure_api(dashboard, monkeypatch, ledger)
    assert body(dashboard) == []


def test_recent_outcomes_error_withholds_database_diagnostics(dashboard_server_module, monkeypatch):
    dashboard, _ = dashboard_server_module
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("private database connection diagnostics")
    monkeypatch.setattr(dashboard, "engine", BrokenEngine())
    response, status = dashboard.get_trade_outcomes()
    assert status == 500
    assert response["args"][0] == {"error": "Recorded trade outcomes are unavailable"}
