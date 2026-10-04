"""update_holdings on the scheduled path, end to end in simulation against in-memory SQLite.

One-trade pilot mode limits BUYS to one per cycle and never holds back a sell; the
MAX_POSITION_* / MAX_TOTAL_INVESTMENT* caps bind inside process_buy_decisions (they used to
run only through trading_interface.execute_trade_decisions, which the scheduler never calls).
"""
import sys
import time
import types

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

HASH = "test-hash"
PRICES = {"QCOM": 150.0, "TMO": 500.0, "NVDA": 300.0, "AMD": 100.0, "DE": 677.57}


@pytest.fixture
def decider(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT NOT NULL, ticker TEXT NOT NULL,
                shares FLOAT, purchase_price FLOAT, current_price FLOAT, purchase_timestamp TIMESTAMP,
                current_price_timestamp TIMESTAMP, total_value FLOAT, current_value FLOAT, gain_loss FLOAT,
                reason TEXT, is_active BOOLEAN)
        """))

    cfg = types.ModuleType("config")

    class _PromptManager:
        def __init__(self, *args, **kwargs):
            pass

    cfg.engine = engine
    cfg.PromptManager = _PromptManager
    cfg.session = None
    cfg.openai = None
    cfg.get_agent_model = lambda *a, **k: "stub-model"
    cfg.get_reasoning_params = lambda *a, **k: {}
    cfg.get_current_config_hash = lambda: HASH
    cfg.get_trading_mode = lambda: "simulation"
    cfg.IS_MARGIN_ACCOUNT = False
    cfg.DAILY_TICKET_CAP = 6
    cfg.DAILY_BUY_CAP = 3
    cfg.MIN_ENTRY_SPACING_MIN = 45
    cfg.REENTRY_COOLDOWN_MIN = 240
    cfg.MIN_CASH_BUFFER = 200.0
    cfg.MAX_POSITION_VALUE = 2000.0
    cfg.MAX_POSITION_FRACTION = 0.0
    cfg.MAX_TOTAL_INVESTMENT = 10000.0
    cfg.MAX_TOTAL_INVESTMENT_FRACTION = 0.0
    monkeypatch.setitem(sys.modules, "config", cfg)

    feedback = types.ModuleType("feedback_agent")

    class _Tracker:
        def record_sell_outcome(self, *args, **kwargs):
            return "stub"

    feedback.TradeOutcomeTracker = _Tracker
    monkeypatch.setitem(sys.modules, "feedback_agent", feedback)

    monkeypatch.delenv("DAI_ONE_TRADE_MODE", raising=False)
    monkeypatch.setenv("DAI_MAX_BUY_AMOUNT", "2500")
    monkeypatch.delitem(sys.modules, "decider_agent", raising=False)
    import decider_agent as da

    monkeypatch.setattr(da, "is_market_open", lambda: True)
    monkeypatch.setattr(da, "get_current_price", lambda t: PRICES.get(da.clean_ticker_symbol(t)))
    monkeypatch.setattr(da.price_fetcher, "prefetch_prices", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda *_: None)   # the 30 s sell→buy settle wait
    yield da, engine
    monkeypatch.delitem(sys.modules, "decider_agent", raising=False)


def _seed(engine, cash, positions):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, total_value,
                                  current_value, gain_loss, reason, is_active)
            VALUES (:h, 'CASH', 1, :c, :c, :c, :c, 0, 'cash', TRUE)
        """), {"h": HASH, "c": cash})
        for ticker, shares in positions.items():
            px = PRICES[ticker]
            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, total_value,
                                      current_value, gain_loss, reason, is_active)
                VALUES (:h, :t, :s, :p, :p, :v, :v, 0, 'thesis', TRUE)
            """), {"h": HASH, "t": ticker, "s": shares, "p": px, "v": shares * px})


def _book(engine):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT ticker, shares, is_active, current_value FROM holdings WHERE config_hash = :h"
        ), {"h": HASH}).fetchall()
    return {r.ticker: r for r in rows}


def test_pilot_mode_executes_sells_and_only_the_first_buy(decider, monkeypatch):
    da, engine = decider
    monkeypatch.setenv("DAI_ONE_TRADE_MODE", "1")
    _seed(engine, 5000.0, {"QCOM": 5, "TMO": 2})
    decisions = [
        {"action": "sell", "ticker": "QCOM", "amount_usd": 0, "reason": "profit-taking +3%"},
        {"action": "sell", "ticker": "TMO", "amount_usd": 0, "reason": "kill breach"},
        {"action": "buy", "ticker": "NVDA", "amount_usd": 900, "reason": "setup A"},
        {"action": "buy", "ticker": "AMD", "amount_usd": 500, "reason": "setup B"},
    ]
    skipped = da.update_holdings(decisions)
    book = _book(engine)
    assert not book["QCOM"].is_active and not book["TMO"].is_active      # both exits executed
    assert book["NVDA"].shares == 3 and "AMD" not in book                 # one buy only
    amd = next(s for s in skipped if s.get("ticker") == "AMD")
    assert "pilot" in amd["reason"] and amd["execution_status"] == "not_executed"
    assert not any(s.get("action") == "sell" for s in skipped)


def test_position_cap_trims_a_buy_and_counts_the_existing_position(decider, monkeypatch):
    da, engine = decider
    persisted = []
    monkeypatch.setattr(da, "_persist_execution_outcomes", lambda decisions, *a: persisted.extend(decisions))
    _seed(engine, 6000.0, {"NVDA": 5})                     # $1,500 of NVDA held, $2,000 cap
    da.update_holdings([{"action": "buy", "ticker": "NVDA", "amount_usd": 1200, "reason": "add"}])
    assert _book(engine)["NVDA"].shares == 6               # +1 share ($300), not +4
    (nvda,) = persisted
    assert nvda["sizing"]["bound_by"] == "position cap" and nvda["sizing"]["cap_usd"] == 2000
    assert nvda["shares_override"] == 1 and nvda["amount_usd_requested"] == 1200


def test_cap_skip_gives_a_plain_reason_with_the_dollar_value(decider):
    da, engine = decider
    _seed(engine, 6000.0, {"DE": 2})                       # $1,355.14 of DE held under the $2,000 cap
    skipped = da.update_holdings([{"action": "buy", "ticker": "DE", "amount_usd": 400, "reason": "half size"}])
    de = next(s for s in skipped if s.get("ticker") == "DE")
    assert "$2,000.00 position cap" in de["reason"] and _book(engine)["DE"].shares == 2


def test_total_investment_cap_counts_buys_earlier_in_the_cycle(decider, monkeypatch):
    da, engine = decider
    monkeypatch.setattr(da, "MAX_TOTAL_INVESTMENT", 2000.0)
    _seed(engine, 6000.0, {})
    skipped = da.update_holdings([
        {"action": "buy", "ticker": "NVDA", "amount_usd": 1800, "reason": "first"},   # 6 sh = $1,800
        {"action": "buy", "ticker": "AMD", "amount_usd": 500, "reason": "second"},    # $200 room → 2 sh
    ])
    book = _book(engine)
    assert book["NVDA"].shares == 6 and book["AMD"].shares == 2
    assert not any(s.get("ticker") in ("NVDA", "AMD") for s in skipped)


def test_a_cap_book_error_falls_back_to_todays_sizing(decider, monkeypatch):
    da, engine = decider

    def _boom(*args, **kwargs):
        raise RuntimeError("holdings read failed")

    monkeypatch.setattr(da, "_position_cap_book", _boom)
    _seed(engine, 6000.0, {"NVDA": 5})
    da.update_holdings([{"action": "buy", "ticker": "NVDA", "amount_usd": 1200, "reason": "add"}])
    assert _book(engine)["NVDA"].shares == 9               # uncapped: +4 shares, as before this change
