"""Whole-share sizing: a sub-share ticket rounds up to one share inside the rails, else skips with a plain reason.

Also the MAX_POSITION_* / MAX_TOTAL_INVESTMENT* caps on the scheduled buy path and the per-cycle
ticket split (one-trade pilot mode limits buys only)."""
import math
import sys
import types

from order_sizing import CapBook, PositionCaps, resolve_cap, split_cycle_tickets, whole_share_allocation


def test_allocation_that_buys_whole_shares_is_unchanged():
    r = whole_share_allocation(1000, 250.0, 2173.29, max_buy=2500, min_buffer=100)
    assert (r.shares, r.bound_by) == (4, "model allocation")


def test_de_case_rounds_up_to_one_share_inside_the_rails():
    # 2026-09-17: $400 half-size ticket, DE at $677.57, $2,173.29 settled → used to skip as "have $400.00"
    r = whole_share_allocation(400, 677.57, 2173.29, max_buy=2500, min_buffer=100)
    assert (r.shares, r.bound_by) == (1, "one-share minimum")
    assert "rounded up to 1 share" in r.note and "$677.57" in r.note


def test_one_share_above_the_max_rail_is_skipped_and_says_so():
    r = whole_share_allocation(400, 2600.0, 9000.0, max_buy=2500, min_buffer=100)
    assert r.shares == 0 and r.bound_by == "max rail" and "MAX rail" in r.note


def test_one_share_beyond_settled_funds_behind_the_buffer_is_skipped():
    r = whole_share_allocation(400, 677.57, 700.0, max_buy=2500, min_buffer=100)   # $600 spendable
    assert r.shares == 0 and r.bound_by == "settled funds" and "$600.00" in r.note


def test_missing_price_never_sizes():
    assert whole_share_allocation(400, 0.0, 2000.0, max_buy=2500, min_buffer=100).shares == 0


# --- position / total-investment caps (MAX_POSITION_* / MAX_TOTAL_INVESTMENT*) -------------

def test_resolve_cap_is_max_of_floor_and_fraction():
    assert resolve_cap(2000, 0, 50000) == 2000                 # fraction unset → floor
    assert resolve_cap(2000, 0.25, 4000) == 2000               # floor larger
    assert resolve_cap(2000, 0.25, 20000) == 5000              # fraction larger
    assert resolve_cap(0, 0.25, 20000) == 5000                 # floor unset → fraction
    assert math.isinf(resolve_cap(0, 0, 20000))                # neither set → no cap
    assert resolve_cap(2000, 0.25, 0) == 2000                  # no account value → floor only


def test_safety_manager_resolvers_share_the_same_rule(monkeypatch):
    """TradingSafetyManager delegates to resolve_cap, so both paths agree on the max-of semantics."""
    cfg = types.ModuleType("config")
    cfg.engine = object()
    cfg.MAX_POSITION_VALUE, cfg.MAX_POSITION_FRACTION = 2000.0, 0.25
    cfg.MAX_TOTAL_INVESTMENT, cfg.MAX_TOTAL_INVESTMENT_FRACTION = 10000.0, 0.9
    cfg.MIN_CASH_BUFFER, cfg.DEBUG_TRADING = 200.0, False
    cfg.get_current_config_hash = lambda: "h"
    monkeypatch.setitem(sys.modules, "config", cfg)
    monkeypatch.delitem(sys.modules, "safety_checks", raising=False)
    import safety_checks
    mgr = safety_checks.TradingSafetyManager()
    assert mgr._resolve_position_limit(20000, 1000) == resolve_cap(2000, 0.25, 20000) == 5000
    assert mgr._resolve_total_investment_limit(20000, 1000) == resolve_cap(10000, 0.9, 20000) == 18000
    assert mgr._resolve_position_limit(0, 4000) == 2000          # no portfolio value → cash as account value
    monkeypatch.delitem(sys.modules, "safety_checks", raising=False)


def test_caps_that_do_not_bind_leave_the_allocation_alone():
    caps = PositionCaps(position_limit=2000, total_limit=10000, existing_position=0, invested=1500)
    r = whole_share_allocation(1000, 250.0, 2173.29, max_buy=2500, min_buffer=100, caps=caps)
    assert (r.shares, r.bound_by, r.cap_usd) == (4, "model allocation", None)


def test_position_cap_cuts_a_full_share_ticket_and_names_itself():
    # $2,400 at $300 = 8 shares, but the $2,000 position cap fits 6
    caps = PositionCaps(position_limit=2000, total_limit=10000)
    r = whole_share_allocation(2400, 300.0, 5000, max_buy=2500, min_buffer=200, caps=caps)
    assert (r.shares, r.bound_by, r.cap_usd) == (6, "position cap", 2000)
    assert "$2,000.00 position cap" in r.note and "cut from 8" in r.note


def test_existing_position_counts_against_the_position_cap():
    # already hold $1,500 of the name: $500 of room → 1 share at $300, not 3
    caps = PositionCaps(position_limit=2000, total_limit=10000, existing_position=1500, invested=1500)
    r = whole_share_allocation(900, 300.0, 5000, max_buy=2500, min_buffer=200, caps=caps)
    assert (r.shares, r.bound_by) == (1, "position cap")
    assert "$1,500.00 already held" in r.note
    # nearly at the cap: skip, with the cap and its dollar value in the reason
    full = PositionCaps(position_limit=2000, total_limit=10000, existing_position=1950, invested=1950)
    s = whole_share_allocation(900, 300.0, 5000, max_buy=2500, min_buffer=200, caps=full)
    assert s.shares == 0 and s.bound_by == "position cap" and "$2,000.00 position cap" in s.note


def test_total_investment_cap_binds_when_tighter_than_the_position_cap():
    caps = PositionCaps(position_limit=2000, total_limit=3000, existing_position=0, invested=2400)
    r = whole_share_allocation(1500, 250.0, 5000, max_buy=2500, min_buffer=200, caps=caps)
    assert (r.shares, r.bound_by, r.cap_usd) == (2, "total investment cap", 3000)
    assert "$3,000.00 total investment cap" in r.note and "$2,400.00 already invested" in r.note


def test_round_up_is_blocked_when_one_share_breaks_the_position_cap():
    # the DE case again, with $1,500 of DE already held under a $2,000 cap: one more share ($677.57) doesn't fit
    caps = PositionCaps(position_limit=2000, total_limit=10000, existing_position=1500, invested=1500)
    r = whole_share_allocation(400, 677.57, 2173.29, max_buy=2500, min_buffer=100, caps=caps)
    assert r.shares == 0 and r.bound_by == "position cap" and r.cap_usd == 2000
    assert "one share costs more than the $500.00 left under the $2,000.00 position cap" in r.note


def test_round_up_is_blocked_when_one_share_breaks_the_total_cap():
    caps = PositionCaps(position_limit=2000, total_limit=3000, existing_position=0, invested=2600)
    r = whole_share_allocation(400, 677.57, 2173.29, max_buy=2500, min_buffer=100, caps=caps)
    assert r.shares == 0 and r.bound_by == "total investment cap" and "$3,000.00 total investment cap" in r.note


def test_round_up_still_happens_when_one_share_fits_both_caps():
    caps = PositionCaps(position_limit=2000, total_limit=10000, existing_position=0, invested=1400)
    r = whole_share_allocation(400, 677.57, 2173.29, max_buy=2500, min_buffer=100, caps=caps)
    assert (r.shares, r.bound_by) == (1, "one-share minimum")


def test_a_room_of_exactly_n_shares_fits_n_shares():
    # 0.3 / 0.1 is 2.9999999999999996 in floating point; the cap must still fit 3 shares
    caps = PositionCaps(position_limit=0.3, total_limit=math.inf)
    r = whole_share_allocation(10, 0.1, 100, max_buy=2500, min_buffer=0, caps=caps)
    assert (r.shares, r.bound_by) == (3, "position cap")


def test_cap_book_counts_existing_positions_and_earlier_buys_this_cycle():
    book = CapBook.build({"qcom": 743.74, "TMO": 653.55}, 1819.86,
                         max_position_value=2000, max_position_fraction=0,
                         max_total_investment=2000, max_total_investment_fraction=0)
    assert round(book.account_value, 2) == 3217.15 and round(book.invested, 2) == 1397.29
    assert book.caps_for("QCOM").existing_position == 743.74
    book.record_buy("NVDA", 500)
    caps = book.caps_for("AMD")
    assert caps.existing_position == 0 and round(caps.invested, 2) == 1897.29
    r = whole_share_allocation(400, 150.0, 1800, max_buy=2500, min_buffer=200, caps=caps)
    assert r.shares == 0 and r.bound_by == "total investment cap"     # $102.71 of room < $150


def test_cap_book_resolves_fractions_against_the_snapshot_account_value():
    book = CapBook.build({"QCOM": 1000}, 500, account_value=20000, source="Schwab snapshot",
                         max_position_value=2000, max_position_fraction=0.25,
                         max_total_investment=10000, max_total_investment_fraction=0)
    assert (book.position_limit, book.total_limit, book.account_value) == (5000, 10000, 20000)
    assert "Schwab snapshot" in book.describe()


def test_cap_book_with_no_caps_set_never_binds():
    book = CapBook.build({"QCOM": 1000}, 500, max_position_value=0, max_position_fraction=0,
                         max_total_investment=0, max_total_investment_fraction=0)
    r = whole_share_allocation(3000, 100.0, 5000, max_buy=4000, min_buffer=200, caps=book.caps_for("QCOM"))
    assert (r.shares, r.bound_by) == (30, "model allocation")
    assert "none" in book.describe()


# --- per-cycle ticket split: one-trade pilot mode limits BUYS only ---------------------------

def _d(action, ticker):
    return {"action": action, "ticker": ticker}


def test_pilot_mode_executes_every_sell_and_one_buy():
    sells = [_d("sell", "QCOM"), _d("sell", "TMO")]
    buys = [_d("buy", "NVDA"), _d("buy", "AMD")]
    split = split_cycle_tickets(sells, buys, sell_cap=6, buy_cap=3, one_trade_mode=True, live=True)
    assert [d["ticker"] for d in split.sells] == ["QCOM", "TMO"]           # profit-taking / kill exits run
    assert [d["ticker"] for d in split.buys] == ["NVDA"]                   # first buy in decision order
    assert split.pilot_binds and split.buy_limit == 1
    (dropped, error, reason), = split.dropped
    assert dropped["ticker"] == "AMD" and "pilot" in error and "1 buy per cycle" in reason


def test_pilot_mode_sells_still_respect_the_ticket_cap():
    sells = [_d("sell", t) for t in ("A", "B", "C")]
    split = split_cycle_tickets(sells, [], sell_cap=2, buy_cap=3, one_trade_mode=True, live=True)
    assert [d["ticker"] for d in split.sells] == ["A", "B"]
    (dropped, error, _), = split.dropped
    assert dropped["ticker"] == "C" and "2-sell cap" in error


def test_pilot_mode_takes_the_min_with_a_zero_buy_cap():
    split = split_cycle_tickets([], [_d("buy", "NVDA")], sell_cap=6, buy_cap=0, one_trade_mode=True, live=True)
    assert split.buys == [] and not split.pilot_binds
    assert "0-buy cap" in split.dropped[0][1]


def test_pilot_mode_in_simulation_limits_buys_but_not_sells():
    sells = [_d("sell", t) for t in "ABCDEFGH"]
    buys = [_d("buy", "X"), _d("buy", "Y")]
    split = split_cycle_tickets(sells, buys, sell_cap=6, buy_cap=3, one_trade_mode=True, live=False)
    assert len(split.sells) == 8 and [d["ticker"] for d in split.buys] == ["X"]


def test_without_pilot_mode_live_caps_apply_and_simulation_is_uncapped():
    sells = [_d("sell", t) for t in "ABC"]
    buys = [_d("buy", t) for t in "XYZW"]
    live = split_cycle_tickets(sells, buys, sell_cap=2, buy_cap=3, one_trade_mode=False, live=True)
    assert len(live.sells) == 2 and len(live.buys) == 3 and len(live.dropped) == 2
    assert any("3-buy cap" in e for _, e, _ in live.dropped)
    sim = split_cycle_tickets(sells, buys, sell_cap=2, buy_cap=3, one_trade_mode=False, live=False)
    assert len(sim.sells) == 3 and len(sim.buys) == 4 and sim.dropped == []
