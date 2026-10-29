"""Benchmark comparisons share observed endpoints and expose missing cohorts."""
from datetime import datetime, date
import sqlite3

import pytest
from sqlalchemy import create_engine, text

import benchmark_tracker as bt


AS_OF = datetime(2026, 10, 28, 21, 30)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(bt, 'refresh_benchmark_history', lambda *_args, **_kwargs: None)
    eng = create_engine('sqlite://', connect_args={'detect_types': sqlite3.PARSE_DECLTYPES})
    bt.ensure_tables(eng)
    with eng.begin() as conn:
        conn.execute(text('CREATE TABLE portfolio_history (timestamp TIMESTAMP, total_portfolio_value REAL, config_hash TEXT)'))
        conn.execute(text('CREATE TABLE trade_outcomes (ticker TEXT, original_reason TEXT, gain_loss_amount REAL, gain_loss_percentage REAL, config_hash TEXT, sell_timestamp TIMESTAMP)'))
        conn.execute(text('CREATE TABLE model_transitions (model_name TEXT, started_at TIMESTAMP, config_hash TEXT)'))
        for day, value in [(20, 1000), (21, 1010), (23, 1030), (26, 1040), (29, 9000)]:
            conn.execute(text('INSERT INTO portfolio_history VALUES (:at, :v, :cfg)'),
                         {'at': datetime(2026, 10, day, 20), 'v': value, 'cfg': 'cfg'})
        conn.execute(text("INSERT INTO portfolio_history VALUES ('2026-10-28 20:00:00', 100000, 'other')"))
        for symbol in [b['symbol'] for b in bt.BENCHMARKS]:
            for day in [20, 21, 22, 23, 26, 27, 28, 29]:
                if symbol == 'VTI' and day == 20:
                    continue
                if symbol == '^DJI' and day == 22:
                    continue
                conn.execute(text('INSERT INTO benchmark_history VALUES (:s, :d, :v)'),
                             {'s': symbol, 'd': date(2026, 10, day), 'v': 100 + day})
        trades = [
            ('AAA', None, 30, .03, 'cfg', 20), ('BBB', 'entry', -10, -.01, 'cfg', 26),
            ('CCC', None, 5, None, 'cfg', 23), ('DDD', 'entry', None, .005, 'cfg', 25),
            ('EEE', 'entry', None, None, 'cfg', 22),
            ('N/A', 'placeholder', 999, .99, 'cfg', 22), ('AAA', 'MARKET IS CLOSED', 999, .99, 'cfg', 22),
            ('AAA', 'entry', 999, .99, 'other', 22), ('AAA', 'entry', 999, .99, 'cfg', 29),
            ('AAA', 'entry', 999, .99, 'cfg', 27),
        ]
        for ticker, reason, gain, fraction, cfg, day in trades:
            conn.execute(text('INSERT INTO trade_outcomes VALUES (:t, :r, :g, :p, :c, :at)'),
                         {'t': ticker, 'r': reason, 'g': gain, 'p': fraction, 'c': cfg, 'at': datetime(2026, 10, day, 15)})
    yield eng
    eng.dispose()


def test_common_endpoints_do_not_extend_stale_portfolio_or_hide_internal_gaps(engine):
    result = bt.get_benchmark_performance(engine, 'cfg', days=30, sync_flows=False, as_of=AS_OF)
    assert 'error' not in result
    assert result['series']['dates'] == ['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-26']
    assert result['series']['portfolio'][2] is None
    assert result['stats']['end'] == '2026-10-26'
    assert result['stats']['portfolio']['return_pct'] == 4
    assert result['stats']['portfolio']['sharpe'] is None
    coverage = result['stats']['coverage']
    assert coverage['missing_portfolio_sessions'] == ['2026-10-22']
    assert coverage['portfolio_last_snapshot'] == '2026-10-26'
    assert coverage['benchmark_last_date'] == '2026-10-28'
    assert coverage['unavailable_benchmarks'] == ['VTI']
    assert 'VTI' not in result['series']
    assert result['stats']['benchmarks']['^DJI']['missing_sessions'] == 1


def test_trade_metrics_use_same_chart_dates_scope_and_recorded_closure_eligibility(engine):
    result = bt.get_benchmark_performance(engine, 'cfg', days=30, sync_flows=False, as_of=AS_OF)
    trades = result['stats']['trade']
    assert trades['trades'] == 5
    assert trades['scored_trades'] == 3 and trades['amount_scored_trades'] == 3
    assert trades['profit_factor'] == 3.5
    assert trades['expectancy_pct'] == pytest.approx(.025 / 3 * 100)
    assert result['stats']['trade_window']['start'] == '2026-10-20T00:00:00'
    assert result['stats']['trade_window']['end_exclusive'] == '2026-10-27T00:00:00'


def test_nonfinite_portfolio_snapshot_is_reported_not_propagated(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolio_history VALUES ('2026-10-26 21:00:00', NULL, 'cfg')"))
    result = bt.get_benchmark_performance(engine, 'cfg', days=30, sync_flows=False, as_of=AS_OF)
    assert result['stats']['coverage']['invalid_portfolio_snapshots'] == 1
    assert result['stats']['portfolio']['return_pct'] == 4
