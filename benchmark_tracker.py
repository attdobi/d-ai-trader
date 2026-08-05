"""Benchmark-relative performance for the feedback dashboard.

Answers "is the algorithm actually beating the market?" by comparing the
system's growth curve against SPY / DJIA / NASDAQ / VTI over the same window.

Three pieces:
  1. benchmark_history table — daily (dividend-adjusted where applicable)
     closes cached from yfinance, refreshed at most once per REFRESH_TTL.
  2. external_cash_flows table — deposits/withdrawals/journals pulled from the
     Schwab transactions API. These are NOT performance and must be stripped
     before comparing to an index (a $1,000 deposit is not a 40% "gain").
  3. Pure math: daily time-weighted return (TWR) index for the portfolio with
     flow adjustment, benchmark growth indexes, and summary stats (alpha,
     Sharpe, max drawdown, profit factor, expectancy, payoff ratio).

The trader process never imports this; it is dashboard-only.
"""

import os
import time
import hashlib
from datetime import datetime, timedelta, date as date_type

from sqlalchemy import text

# Fixed display order — chart colors are assigned by position, never cycled.
BENCHMARKS = [
    {"symbol": "SPY", "label": "SPY (S&P 500)"},
    {"symbol": "^DJI", "label": "DJIA"},
    {"symbol": "^IXIC", "label": "NASDAQ"},
    {"symbol": "VTI", "label": "VTI (Total Market)"},
]

_env_symbols = os.getenv("DAI_BENCHMARK_SYMBOLS", "").strip()
if _env_symbols:
    BENCHMARKS = [
        {"symbol": s.strip(), "label": s.strip().lstrip("^")}
        for s in _env_symbols.split(",") if s.strip()
    ]

# Schwab transaction types that are external money movement (not performance).
# DIVIDEND_OR_INTEREST and TRADE stay OUT of this set on purpose: dividends and
# realized P&L ARE performance.
EXTERNAL_FLOW_TYPES = {
    "JOURNAL", "ELECTRONIC_FUND", "WIRE_IN", "WIRE_OUT",
    "CASH_RECEIPT", "CASH_DISBURSEMENT",
}

REFRESH_TTL_SECONDS = int(os.getenv("DAI_BENCHMARK_REFRESH_TTL", "21600"))  # 6h
_last_refresh = {"benchmarks": 0.0, "flows": 0.0}


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

def ensure_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS benchmark_history (
                symbol TEXT NOT NULL,
                date DATE NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (symbol, date)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS external_cash_flows (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                txn_key TEXT UNIQUE NOT NULL,
                flow_date DATE NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                description TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))


# --------------------------------------------------------------------------
# Data refresh (guarded by TTL so dashboard requests stay fast)
# --------------------------------------------------------------------------

def refresh_benchmark_history(engine, lookback_days=430, force=False):
    """Upsert daily closes for all benchmarks from yfinance."""
    now = time.time()
    if not force and now - _last_refresh["benchmarks"] < REFRESH_TTL_SECONDS:
        return
    _last_refresh["benchmarks"] = now  # set first: a failing feed shouldn't hammer

    import yfinance as yf  # lazy: keeps module importable in tests without network

    symbols = [b["symbol"] for b in BENCHMARKS]
    start = datetime.utcnow().date() - timedelta(days=lookback_days)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT max(date) FROM benchmark_history WHERE symbol = :s"
            ), {"s": symbols[0]}).scalar()
        if row:
            # small overlap re-fetch so late adjustments correct themselves
            start = max(start, row - timedelta(days=7))
    except Exception:
        pass

    try:
        # auto_adjust=True → dividend/split-adjusted closes for the ETFs, so the
        # comparison to a dividend-receiving portfolio is fair. (^DJI/^IXIC are
        # price indexes; nothing to adjust.)
        frame = yf.download(symbols, start=start.isoformat(), auto_adjust=True,
                            progress=False)["Close"]
    except Exception as e:
        print(f"⚠️  Benchmark fetch failed ({e}); keeping cached history")
        return

    if frame is None or frame.empty:
        return
    if len(symbols) == 1:  # single-symbol download returns a Series
        frame = frame.to_frame(name=symbols[0])

    with engine.begin() as conn:
        for symbol in symbols:
            if symbol not in frame.columns:
                continue
            series = frame[symbol].dropna()
            for idx, close in series.items():
                conn.execute(text("""
                    INSERT INTO benchmark_history (symbol, date, close)
                    VALUES (:symbol, :date, :close)
                    ON CONFLICT (symbol, date) DO UPDATE SET close = EXCLUDED.close
                """), {"symbol": symbol, "date": idx.date(), "close": float(close)})


def refresh_cash_flows(engine, config_hash, force=False):
    """Pull external transfers (deposits/withdrawals/journals) from Schwab."""
    now = time.time()
    if not force and now - _last_refresh["flows"] < REFRESH_TTL_SECONDS:
        return
    _last_refresh["flows"] = now

    try:
        from schwab_client import schwab_client
        if not schwab_client.ensure_authenticated() or not schwab_client.client:
            return
    except Exception as e:
        print(f"⚠️  Schwab unavailable for cash-flow sync: {e}")
        return

    with engine.connect() as conn:
        last = conn.execute(text(
            "SELECT max(flow_date) FROM external_cash_flows WHERE config_hash = :c"
        ), {"c": config_hash}).scalar()
        first_snapshot = conn.execute(text(
            "SELECT min(timestamp) FROM portfolio_history WHERE config_hash = :c"
        ), {"c": config_hash}).scalar()

    if last:
        start = datetime.combine(last, datetime.min.time()) - timedelta(days=7)
    elif first_snapshot:
        start = first_snapshot - timedelta(days=3)
    else:
        start = datetime.utcnow() - timedelta(days=180)

    try:
        resp = schwab_client.client.get_transactions(
            schwab_client.account_hash,
            start_date=start, end_date=datetime.utcnow(),
        )
        if resp.status_code != 200:
            print(f"⚠️  Schwab transactions HTTP {resp.status_code}; keeping cached flows")
            return
        txns = resp.json() or []
    except Exception as e:
        print(f"⚠️  Schwab transactions fetch failed: {e}")
        return

    with engine.begin() as conn:
        for t in txns:
            if t.get("type") not in EXTERNAL_FLOW_TYPES:
                continue
            amount = t.get("netAmount")
            when = t.get("time") or t.get("tradeDate")
            if amount in (None, 0) or not when:
                continue
            key = str(t.get("activityId") or "")
            if not key:
                key = hashlib.sha1(f"{when}|{amount}|{t.get('description','')}".encode()).hexdigest()
            conn.execute(text("""
                INSERT INTO external_cash_flows (config_hash, txn_key, flow_date, amount, description)
                VALUES (:c, :k, :d, :a, :desc)
                ON CONFLICT (txn_key) DO NOTHING
            """), {
                "c": config_hash,
                "k": key,
                "d": str(when)[:10],
                "a": float(amount),
                "desc": (t.get("description") or "")[:200],
            })


# --------------------------------------------------------------------------
# Pure math (no DB, unit-tested in tests/test_benchmark_math.py)
# --------------------------------------------------------------------------

def last_value_per_day(rows):
    """[(timestamp, value)] (any order) -> [(date, last value that date)] sorted."""
    by_day = {}
    for ts, value in sorted(rows, key=lambda r: r[0]):
        # datetime subclasses date, so check datetime explicitly
        day = ts.date() if isinstance(ts, datetime) else ts
        by_day[day] = float(value)
    return sorted(by_day.items())


def filter_artifact_days(daily_values, flows_by_date, threshold=0.15):
    """Drop flowless V-shaped outliers from a daily value series.

    The settled-cash writer bug wrote end-of-day snapshots missing unsettled
    cash (25-50%% dips that fully recover at the next real snapshot). Writers
    are fixed, but surviving historical rows would still poison compounded
    TWR (a fake -25%%/+33%% pair costs ~8%% of the index). A day is treated as
    an artifact when it sits > threshold below BOTH neighbors and no external
    flow could explain it; its value is replaced by carry-forward.

    Returns (cleaned_daily_values, artifact_days).
    """
    if len(daily_values) < 3:
        return daily_values, []
    cleaned = list(daily_values)
    artifacts = []
    for i in range(1, len(cleaned) - 1):
        prev_v = cleaned[i - 1][1]
        day, v = cleaned[i]
        next_v = cleaned[i + 1][1]
        if prev_v <= 0 or next_v <= 0 or v <= 0:
            continue
        flow_nearby = any(
            cleaned[i - 1][0] < d <= cleaned[i + 1][0]
            for d in flows_by_date
        )
        if flow_nearby:
            continue
        if v < prev_v * (1 - threshold) and v < next_v * (1 - threshold):
            cleaned[i] = (day, prev_v)
            artifacts.append(day)
    return cleaned, artifacts


def twr_daily_returns(daily_values, flows_by_date, settle_days=3):
    """Flow-adjusted daily returns: r_t = (V_t - F_t) / V_{t-1} - 1.

    F_t is the net external flow attributed to step t (deposit positive).
    Subtracting it from the end value credits the day's market move but not
    the transfer.

    Attribution is settlement-aware: a Schwab transfer is *dated* when it is
    initiated but often only moves liquidationValue a day later, so pinning
    the flow to its calendar day fabricates a huge fake gain followed by a
    huge fake loss. Each flow is instead assigned to the step (within
    [flow_date, flow_date + settle_days]) whose raw value change it explains
    best (argmin |dV - flow|). Returns [(date, r)] from the SECOND date on.
    """
    steps = []
    for (prev_day, prev_v), (day, v) in zip(daily_values, daily_values[1:]):
        steps.append({"prev_day": prev_day, "day": day, "prev_v": prev_v,
                      "v": v, "flow": 0.0})

    horizon = timedelta(days=settle_days)
    grace = timedelta(days=1)  # UTC-dated evening transfers land in the prior PT day
    flow_candidates = []
    for flow_date, amount in sorted(flows_by_date.items()):
        candidates = [
            i for i, s in enumerate(steps)
            if s["day"] >= flow_date - grace and s["prev_day"] <= flow_date + horizon
        ]
        if candidates:  # else: flow not yet visible in the value series (e.g. today)
            flow_candidates.append((amount, candidates))

    _assign_flows_to_steps(steps, flow_candidates)

    out = []
    for s in steps:
        if s["prev_v"] and s["prev_v"] > 0:
            out.append((s["day"], (s["v"] - s["flow"]) / s["prev_v"] - 1.0))
        else:
            out.append((s["day"], 0.0))
    return out


def _assign_flows_to_steps(steps, flow_candidates, max_combos=50000):
    """Assign each flow to one of its candidate steps.

    Transfers cluster (out one day, in the next), and a greedy per-flow pick
    routinely explains one step's change with the wrong flow, fabricating a
    +25%/-27% whipsaw. With few flows per window an exhaustive search over
    the joint assignment minimizing total unexplained value change is cheap
    and exact; fall back to greedy only if the combination count explodes.
    """
    import itertools

    if not flow_candidates:
        return
    combos = 1
    for _, cands in flow_candidates:
        combos *= len(cands)

    def residual(assignment):
        assigned = {}
        for (amount, _), step_i in zip(flow_candidates, assignment):
            assigned[step_i] = assigned.get(step_i, 0.0) + amount
        total = 0.0
        for i, s in enumerate(steps):
            total += abs((s["v"] - s["prev_v"]) - assigned.get(i, 0.0))
        return total

    if combos <= max_combos:
        best = min(itertools.product(*[c for _, c in flow_candidates]), key=residual)
        for (amount, _), step_i in zip(flow_candidates, best):
            steps[step_i]["flow"] += amount
    else:
        for amount, cands in flow_candidates:
            best_i = min(cands, key=lambda i: abs(
                (steps[i]["v"] - steps[i]["prev_v"] - steps[i]["flow"]) - amount))
            steps[best_i]["flow"] += amount


def chain_index(daily_returns, base=100.0):
    """[(date, r)] -> [(date, index)] with index[0] date implied by caller."""
    idx, out = base, []
    for day, r in daily_returns:
        idx *= (1.0 + r)
        out.append((day, idx))
    return out


def growth_index_from_closes(closes):
    """[(date, close)] sorted -> [(date, index base 100)]."""
    if not closes:
        return []
    base = closes[0][1]
    if not base:
        return []
    return [(d, 100.0 * c / base) for d, c in closes]


def max_drawdown(index_series):
    """Max peak-to-trough decline of an index series, as a negative percent."""
    peak, worst = float("-inf"), 0.0
    for _, v in index_series:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return worst * 100.0


def sharpe_ratio(daily_returns, periods_per_year=252):
    """Annualized Sharpe (rf=0) from [(date, r)]. None if not enough data."""
    rs = [r for _, r in daily_returns]
    if len(rs) < 5:
        return None
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    std = var ** 0.5
    if std == 0:
        return None
    return (mean / std) * (periods_per_year ** 0.5)


def trade_stats(outcomes):
    """Profit factor / expectancy / payoff from [(gain_amount, gain_fraction)]."""
    if not outcomes:
        return {"trades": 0}
    wins = [(a, p) for a, p in outcomes if a > 0]
    losses = [(a, p) for a, p in outcomes if a < 0]
    gross_win = sum(a for a, _ in wins)
    gross_loss = abs(sum(a for a, _ in losses))
    avg_win_pct = (sum(p for _, p in wins) / len(wins) * 100.0) if wins else 0.0
    avg_loss_pct = (sum(p for _, p in losses) / len(losses) * 100.0) if losses else 0.0
    return {
        "trades": len(outcomes),
        "win_rate": len(wins) / len(outcomes) * 100.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "expectancy_pct": sum(p for _, p in outcomes) / len(outcomes) * 100.0,
        "payoff_ratio": (avg_win_pct / abs(avg_loss_pct)) if avg_loss_pct else None,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
    }


# --------------------------------------------------------------------------
# Orchestration (called by the /api/feedback/benchmarks endpoint)
# --------------------------------------------------------------------------

def get_benchmark_performance(engine, config_hash, days=90):
    ensure_tables(engine)
    refresh_benchmark_history(engine)
    refresh_cash_flows(engine, config_hash)

    window_start = datetime.utcnow().date() - timedelta(days=days)

    with engine.connect() as conn:
        snap_rows = conn.execute(text("""
            SELECT timestamp, total_portfolio_value FROM portfolio_history
            WHERE config_hash = :c AND timestamp >= :start
            ORDER BY timestamp
        """), {"c": config_hash, "start": window_start - timedelta(days=5)}).fetchall()

        flow_rows = conn.execute(text("""
            SELECT flow_date, amount, description FROM external_cash_flows
            WHERE config_hash = :c AND flow_date >= :start
            ORDER BY flow_date
        """), {"c": config_hash, "start": window_start - timedelta(days=5)}).fetchall()

        bench_rows = conn.execute(text("""
            SELECT symbol, date, close FROM benchmark_history
            WHERE date >= :start ORDER BY date
        """), {"start": window_start - timedelta(days=5)}).fetchall()

        outcome_rows = conn.execute(text("""
            SELECT gain_loss_amount, gain_loss_percentage FROM trade_outcomes
            WHERE config_hash = :c AND sell_timestamp >= :start
        """), {"c": config_hash, "start": window_start}).fetchall()

        # Decider model switches (config hash stays fixed across model upgrades,
        # so this table is the only record of when the brain changed).
        transition_rows = conn.execute(text("""
            SELECT model_name, started_at FROM model_transitions
            WHERE config_hash = :c ORDER BY started_at
        """), {"c": config_hash}).fetchall()

    portfolio_daily = last_value_per_day([(r.timestamp, r.total_portfolio_value) for r in snap_rows])
    if len(portfolio_daily) < 2:
        return {"error": "Not enough portfolio history for this window"}

    closes_by_symbol = {}
    for r in bench_rows:
        closes_by_symbol.setdefault(r.symbol, []).append((r.date, float(r.close)))

    # Common timeline = benchmark trading days inside the window that the
    # portfolio can cover; the portfolio value carries forward onto each one.
    anchor_symbol = BENCHMARKS[0]["symbol"]
    trading_days = [d for d, _ in closes_by_symbol.get(anchor_symbol, [])
                    if d >= max(window_start, portfolio_daily[0][0])]
    if len(trading_days) < 2:
        return {"error": "Not enough benchmark history for this window"}

    pv_by_day = dict(portfolio_daily)
    all_days = [d for d, _ in portfolio_daily]

    def portfolio_value_on(day):
        if day in pv_by_day:
            return pv_by_day[day]
        prior = [d for d in all_days if d <= day]
        return pv_by_day[prior[-1]] if prior else None

    aligned = []
    for d in trading_days:
        v = portfolio_value_on(d)
        if v is not None:
            aligned.append((d, v))
    if len(aligned) < 2:
        return {"error": "Not enough overlapping history"}

    flows_by_date = {}
    flow_list = []
    for r in flow_rows:
        d = r.flow_date
        flows_by_date[d] = flows_by_date.get(d, 0.0) + float(r.amount)
        flow_list.append({"date": d.isoformat(), "amount": float(r.amount),
                          "description": r.description})

    aligned, artifact_days = filter_artifact_days(aligned, flows_by_date)
    port_returns = twr_daily_returns(aligned, flows_by_date)
    port_index = [(aligned[0][0], 100.0)] + chain_index(port_returns)

    series = {"dates": [d.isoformat() for d, _ in port_index],
              "portfolio": [round(v, 3) for _, v in port_index]}
    bench_stats = {}
    for bench in BENCHMARKS:
        closes = [(d, c) for d, c in closes_by_symbol.get(bench["symbol"], [])
                  if aligned[0][0] <= d <= aligned[-1][0]]
        gi = growth_index_from_closes(closes)
        gi_by_day = dict(gi)
        series[bench["symbol"]] = [
            round(gi_by_day[d], 3) if d in gi_by_day else None
            for d, _ in port_index
        ]
        if gi:
            bench_returns = [(d2, (c2 / c1 - 1.0)) for (d1, c1), (d2, c2) in zip(closes, closes[1:])]
            bench_stats[bench["symbol"]] = {
                "label": bench["label"],
                "return_pct": round(gi[-1][1] - 100.0, 2),
                "sharpe": _round(sharpe_ratio(bench_returns), 2),
                "max_drawdown_pct": round(max_drawdown(gi), 2),
            }

    port_return_pct = port_index[-1][1] - 100.0
    spy = bench_stats.get(anchor_symbol, {})
    stats = {
        "window_days": days,
        "start": aligned[0][0].isoformat(),
        "end": aligned[-1][0].isoformat(),
        "portfolio": {
            "return_pct": round(port_return_pct, 2),
            "sharpe": _round(sharpe_ratio(port_returns), 2),
            "max_drawdown_pct": round(max_drawdown(port_index), 2),
        },
        "alpha_vs": {
            b["symbol"]: round(port_return_pct - bench_stats[b["symbol"]]["return_pct"], 2)
            for b in BENCHMARKS if b["symbol"] in bench_stats
        },
        "benchmarks": bench_stats,
        "trade": trade_stats([(float(r.gain_loss_amount), float(r.gain_loss_percentage))
                              for r in outcome_rows]),
        "external_flows": flow_list,
        "artifact_days_filtered": [d.isoformat() for d in artifact_days],
        # Only switches inside the plotted window get an annotation line; the
        # model already active at window start is reported separately.
        "model_transitions": [
            {"date": r.started_at.date().isoformat(), "model": r.model_name}
            for r in transition_rows
            if aligned[0][0] < r.started_at.date() <= aligned[-1][0]
        ],
        "model_at_start": next(
            (r.model_name for r in reversed(transition_rows)
             if r.started_at.date() <= aligned[0][0]), None),
        "spy_symbol": anchor_symbol,
        "spy_alpha": round(port_return_pct - spy.get("return_pct"), 2) if spy.get("return_pct") is not None else None,
    }
    return {"series": series, "stats": stats,
            "benchmark_order": [{"symbol": b["symbol"], "label": b["label"]} for b in BENCHMARKS]}


def _round(v, n):
    return round(v, n) if v is not None else None
