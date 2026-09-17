"""Whole-share sizing: a sub-share ticket rounds up to one share inside the rails, else skips with a plain reason."""
from order_sizing import whole_share_allocation


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
