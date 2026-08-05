"""Pure-math tests for benchmark_tracker (no DB, no network).

The TWR flow-attribution logic is what keeps a $1,000 deposit from reading as
a +40% trading day, so it gets the bulk of the coverage.
"""
from datetime import date

import benchmark_tracker as bt


def d(day):
    return date(2026, 7, day)


def index_of(returns):
    out = 100.0
    for _, r in returns:
        out *= 1 + r
    return out


def test_flow_on_snapshot_day_is_stripped():
    daily = [(d(1), 1000.0), (d(2), 2005.0), (d(3), 2010.0)]
    rets = bt.twr_daily_returns(daily, {d(2): 1000.0})
    by_day = dict(rets)
    assert abs(by_day[d(2)] - 0.005) < 1e-9  # +$1000 deposit, +0.5% market
    assert abs(index_of(rets) - 100.75) < 0.02


def test_settlement_lag_does_not_fabricate_whipsaw():
    # Withdrawal dated day 2 but only reflected in day 3's value (T+1 posting).
    # Naive same-day attribution would compute +92% then -63%.
    daily = [(d(1), 2400.0), (d(2), 2410.0), (d(3), 560.0)]
    rets = dict(bt.twr_daily_returns(daily, {d(2): -1853.0}))
    assert abs(rets[d(2)] - (2410.0 / 2400.0 - 1)) < 1e-9
    assert abs(rets[d(3)] - ((560.0 + 1853.0) / 2410.0 - 1)) < 1e-9
    assert all(abs(r) < 0.02 for r in rets.values())


def test_utc_dated_evening_flow_lands_in_prior_day_step():
    # Transfer stamped day 3 in UTC actually hit the account during day 2 PT.
    daily = [(d(1), 1000.0), (d(2), 1702.0), (d(3), 1705.0)]
    rets = dict(bt.twr_daily_returns(daily, {d(3): 700.0}))
    assert abs(rets[d(2)] - 0.002) < 1e-9
    assert all(abs(r) < 0.01 for r in rets.values())


def test_transfer_cluster_resolves_jointly():
    # Out -500 one day, in +700+115 the next, +124 journal — all posting into
    # the same step (net +439). Greedy per-flow attribution fabricated a
    # +25%/-27% pair here; joint assignment must keep both days quiet.
    daily = [(d(1), 1479.0), (d(2), 1910.0), (d(3), 1907.0)]
    flows = {d(2): -500.0 + 124.0, d(3): 700.0 + 115.0}
    rets = dict(bt.twr_daily_returns(daily, flows))
    assert all(abs(r) < 0.03 for r in rets.values()), rets


def test_flow_not_yet_visible_is_ignored():
    # Deposit dated after the last snapshot: nothing to attribute it to yet.
    daily = [(d(1), 1000.0), (d(2), 1010.0)]
    rets = dict(bt.twr_daily_returns(daily, {d(5): 500.0}))
    assert abs(rets[d(2)] - 0.01) < 1e-9


def test_artifact_filter_removes_flowless_v_shape():
    daily = [(d(1), 2370.0), (d(2), 1767.0), (d(3), 2379.0)]
    cleaned, artifacts = bt.filter_artifact_days(daily, {})
    assert artifacts == [d(2)]
    assert cleaned[1] == (d(2), 2370.0)


def test_artifact_filter_keeps_flow_explained_dip():
    # Same V-shape but a withdrawal+redeposit explains it: keep the data.
    daily = [(d(1), 2370.0), (d(2), 1767.0), (d(3), 2379.0)]
    cleaned, artifacts = bt.filter_artifact_days(daily, {d(2): -600.0, d(3): 600.0})
    assert artifacts == []
    assert cleaned == daily


def test_artifact_filter_keeps_real_drawdown():
    # A genuine drop that does NOT recover is not an artifact.
    daily = [(d(1), 2370.0), (d(2), 1767.0), (d(3), 1800.0)]
    cleaned, artifacts = bt.filter_artifact_days(daily, {})
    assert artifacts == []
    assert cleaned == daily


def test_max_drawdown():
    series = [(d(1), 100.0), (d(2), 120.0), (d(3), 90.0), (d(4), 110.0)]
    assert abs(bt.max_drawdown(series) - (-25.0)) < 1e-9


def test_growth_index_base_100():
    gi = bt.growth_index_from_closes([(d(1), 50.0), (d(2), 55.0)])
    assert gi[0][1] == 100.0
    assert abs(gi[1][1] - 110.0) < 1e-9


def test_sharpe_sign():
    up = [(d(i), 0.01) for i in range(1, 11)]
    assert bt.sharpe_ratio([(dt, r + 0.001 * (i % 2)) for i, (dt, r) in enumerate(up)]) > 0
    down = [(d(i), -0.01 - 0.001 * (i % 2)) for i in range(1, 11)]
    assert bt.sharpe_ratio(down) < 0


def test_trade_stats():
    # amounts in $, percentages as fractions (matching trade_outcomes storage)
    outcomes = [(30.0, 0.03), (20.0, 0.02), (-10.0, -0.01), (-15.0, -0.015)]
    s = bt.trade_stats(outcomes)
    assert s["trades"] == 4
    assert abs(s["win_rate"] - 50.0) < 1e-9
    assert abs(s["profit_factor"] - 2.0) < 1e-9
    assert abs(s["payoff_ratio"] - 2.0) < 1e-9
    assert abs(s["expectancy_pct"] - 0.625) < 1e-9


def test_last_value_per_day_takes_latest():
    from datetime import datetime
    rows = [
        (datetime(2026, 7, 1, 9, 0), 100.0),
        (datetime(2026, 7, 1, 16, 0), 105.0),
        (datetime(2026, 7, 2, 10, 0), 106.0),
    ]
    assert bt.last_value_per_day(rows) == [(d(1), 105.0), (d(2), 106.0)]
