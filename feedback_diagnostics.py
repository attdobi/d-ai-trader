"""Deterministic trade diagnostics for the RLMF loop (no LLM calls).

The feedback agent, the prompt-evolution generator and the critic all reason
from the same 30-60 closed trades. Eyeballing a "20 best + 20 worst" sample
produced hedged, sample-size-obsessed guidance (see prompt_change_reviews,
Aug 2026) while the two largest measured leaks — same-ticker re-entry churn
and buying "pullbacks" in names 6-18% above their 20-day MA into a momentum
unwind — were only visible when computed over the whole population.

This module computes those numbers in code and renders them as a compact
block injected into all three prompts, so "re-entries are the largest leak"
is a measurement, not an impression.

Public API:
    compute_trade_diagnostics(config_hash, days_back=30) -> dict
    format_diagnostics(diag) -> str      # prompt-ready block ('' when no trades)
    SUPPLIED_DECIDER_FIELDS              # what the Decider actually receives
"""
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text

from config import engine

# What the Decider is actually given each cycle. A rule that gates on anything
# NOT in this list is a cash-lock, not risk control (Decider v20 rejected every
# candidate on 2026-09-02 for lacking a "quoted entry price and fixed kill" that
# nothing supplied). The feedback agent, generator and critic all see this list.
SUPPLIED_DECIDER_FIELDS = (
    "Holdings: ticker, shares, cost basis, current price, $ and % P&L, age (held Xh/Xd), buy reason incl. K:/D:. "
    "Account: settled cash, daily ticket/buy caps used, minutes since last entry, tickers entered today. "
    "Momentum Recap (per ticker in news/holdings): price, 10m/1h/1d/1w/1mo/1y % change, RS vs SPY (10m/1d/1mo), "
    "volume and rel-vol vs 20d avg, day-range position, 52w range. "
    "CONTRARIAN WATCHLIST (screener): price, 20d MA level, setup type, day/wk/mo %, RS vs SPY 5d/20d, RSI, "
    "% from 20d high, % vs 20d MA, rel-vol, EXTENDED tag, suggested 3% kill price. "
    "INDEX REGIME line: SPY and QQQ vs their 20d MA and 5d return, momentum-leader cohort health, label RISK-ON/MIXED/RISK-OFF. "
    "QUARANTINE line: tickers exited within the last 2 sessions. "
    "Summaries: 3 headlines + one insights paragraph per news source. Feedback Snapshot (latest decider_feedback). "
    "LESSONS (long-term memory rows) and RECENT ACTIVITY (own last cycles). "
    "NOT supplied: VWAP, opening range, sector-ETF trends, breadth, options flow, earnings dates, order book."
)

_EXT_PATTERNS = (
    r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:vs\s*20d\s*ma|vs\s*20d|vs20d|over\s*20d|above\s*20d|vs\s*20-day|above\s*20-day|above\s*the\s*20)",
    r"holds?\s*20d\s*\(\+?([+-]?\d+(?:\.\d+)?)%\)",
    r"20d\s*\(\+?([+-]?\d+(?:\.\d+)?)%\)",
)
_MONTH_PATTERNS = (
    r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:mo\b|month)",
    r"(?:mo|month)\s*\+?([+-]?\d+(?:\.\d+)?)",
)
_NUMERIC_KILL = re.compile(
    r"(?:K:|kill|stop)[^;,]*?\$\s*\d|stop\s*[<-]?\s*\$?\d|\(-\d+(?:\.\d+)?%\)|kill\s*(?:at|<)?\s*-?\d+(?:\.\d+)?%|stop\s*-\d+(?:\.\d+)?\s*(?:%|/)|<\s*\$\d",
    re.I,
)


def _num(patterns, s):
    for pat in patterns:
        m = re.search(pat, s or "", re.I)
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def _kill_kind(reason):
    r = reason or ""
    if _NUMERIC_KILL.search(r):
        return "numeric"
    if re.search(r"20\s*-?\s*d", r, re.I):
        return "20d-only"
    return "none"


def _benchmark_regimes(conn):
    """Per-date regime labels from benchmark_history (SPY + NASDAQ proxy).

    RISK-ON  : SPY and NASDAQ above their 20d MA and NASDAQ 5d > -1%
    RISK-OFF : NASDAQ below its 20d MA, or NASDAQ 5d <= -2%, or SPY > 0.5% below its 20d MA
    MIXED    : everything else
    Returns {date: {"label", "spy_vs20d", "nas_vs20d", "nas_5d"}} or {} on failure.
    """
    try:
        symbols = [r[0] for r in conn.execute(text("SELECT DISTINCT symbol FROM benchmark_history")).fetchall()]
    except Exception:
        return {}
    spy = next((s for s in symbols if s.upper() == "SPY"), None)
    nas = next((s for s in ("QQQ", "^IXIC", "NASDAQ", "IXIC") if s in symbols), None)
    if nas is None:
        nas = next((s for s in symbols if "NAS" in s.upper() or "IXIC" in s.upper()), None)
    if not spy:
        return {}

    def _series(sym):
        rows = conn.execute(text(
            "SELECT date, close FROM benchmark_history WHERE symbol = :s ORDER BY date"
        ), {"s": sym}).fetchall()
        out = {}
        closes = [float(r.close) for r in rows]
        for i, r in enumerate(rows):
            if i < 20:
                continue
            sma = sum(closes[i - 19:i + 1]) / 20.0
            out[r.date] = {
                "vs20d": (closes[i] / sma - 1.0) * 100.0 if sma else 0.0,
                "r5": (closes[i] / closes[i - 5] - 1.0) * 100.0 if closes[i - 5] else 0.0,
            }
        return out

    spy_s = _series(spy)
    nas_s = _series(nas) if nas else {}
    regimes = {}
    for d, sv in spy_s.items():
        nv = nas_s.get(d, sv)
        if nv["vs20d"] < 0 or nv["r5"] <= -2.0 or sv["vs20d"] < -0.5:
            label = "RISK-OFF"
        elif sv["vs20d"] > 0 and nv["vs20d"] > 0 and nv["r5"] > -1.0:
            label = "RISK-ON"
        else:
            label = "MIXED"
        regimes[d] = {"label": label, "spy_vs20d": sv["vs20d"], "nas_vs20d": nv["vs20d"], "nas_5d": nv["r5"]}
    return regimes


def _regime_on(regimes, day):
    """Label for `day`, falling back to the nearest prior trading day (max 5 days)."""
    if not regimes:
        return "UNKNOWN"
    for back in range(0, 6):
        rec = regimes.get(day - timedelta(days=back))
        if rec:
            return rec["label"]
    return "UNKNOWN"


def _stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    wins = [r["pct"] for r in rows if r["pct"] > 0]
    return {
        "n": n,
        "win_rate": round(100.0 * len(wins) / n, 0),
        "avg_pct": round(sum(r["pct"] for r in rows) / n, 2),
        "sum_usd": round(sum(r["usd"] for r in rows), 2),
    }


def compute_trade_diagnostics(config_hash, days_back=30, reentry_days=3):
    """Population-level diagnostics over every closed non-synced trade in the window."""
    cutoff = datetime.utcnow() - timedelta(days=int(days_back))
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, sell_timestamp, purchase_price, gain_loss_percentage, gain_loss_amount,
                   hold_duration_days, original_reason, sell_reason
            FROM trade_outcomes
            WHERE config_hash = :h AND sell_timestamp >= :cutoff AND ticker != 'N/A'
              AND COALESCE(original_reason, '') NOT LIKE '%Market is closed%'
            ORDER BY sell_timestamp
        """), {"h": config_hash, "cutoff": cutoff}).fetchall()
        regimes = _benchmark_regimes(conn)

    synced_usd, synced_n = 0.0, 0
    seen, trades = {}, []
    for r in rows:
        reason = r.original_reason or ""
        if "synced" in reason.lower():
            synced_n += 1
            synced_usd += float(r.gain_loss_amount or 0.0)
            continue
        sell_date = r.sell_timestamp.date()
        key = (r.ticker, round(float(r.purchase_price or 0.0), 2), sell_date)
        if key in seen:  # second lot of the same campaign closed the same day
            seen[key]["usd"] += float(r.gain_loss_amount or 0.0)
            seen[key]["lots"] += 1
            continue
        hold = int(r.hold_duration_days or 0)
        entry_date = sell_date - timedelta(days=hold)
        rec = {
            "ticker": r.ticker,
            "sell_date": sell_date,
            "entry_date": entry_date,
            "pct": float(r.gain_loss_percentage or 0.0) * 100.0,
            "usd": float(r.gain_loss_amount or 0.0),
            "hold": hold,
            "lots": 1,
            "ext": _num(_EXT_PATTERNS, reason),
            "month": _num(_MONTH_PATTERNS, reason),
            "kill": _kill_kind(reason),
            "regime": _regime_on(regimes, entry_date),
            "reason": reason[:160],
        }
        seen[key] = rec
        trades.append(rec)

    diag = {
        "window_days": int(days_back),
        "closed_trades": len(rows),
        "campaigns": len(trades),
        "synced": {"n": synced_n, "sum_usd": round(synced_usd, 2)},
        "note": "Campaign = one entry; same-day lot closures merged. Synced/inherited inventory excluded from entry-quality stats.",
    }
    if not trades:
        diag["empty"] = True
        return diag

    # --- payoff geometry -------------------------------------------------
    wins = sorted(t["pct"] for t in trades if t["pct"] > 0)
    losses = sorted(t["pct"] for t in trades if t["pct"] <= 0)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = -sum(losses) / len(losses) if losses else 0.0
    payoff = (avg_win / avg_loss) if avg_loss else None
    breakeven = (avg_loss / (avg_win + avg_loss) * 100.0) if (avg_win + avg_loss) else None
    diag["payoff"] = {
        "win_rate": round(100.0 * len(wins) / len(trades), 1),
        "avg_win_pct": round(avg_win, 2),
        "median_win_pct": round(statistics.median(wins), 2) if wins else None,
        "avg_loss_pct": round(-avg_loss, 2),
        "median_loss_pct": round(statistics.median(losses), 2) if losses else None,
        "payoff_ratio": round(payoff, 2) if payoff else None,
        "breakeven_win_rate": round(breakeven, 1) if breakeven is not None else None,
        "winners_capped_3_to_5pct": round(100.0 * sum(1 for w in wins if 2.5 <= w <= 5.5) / len(wins), 0) if wins else None,
        "worst_5": [(t["ticker"], str(t["sell_date"]), round(t["pct"], 1)) for t in sorted(trades, key=lambda t: t["pct"])[:5]],
        "best_3": [(t["ticker"], str(t["sell_date"]), round(t["pct"], 1)) for t in sorted(trades, key=lambda t: -t["pct"])[:3]],
        "total_usd": round(sum(t["usd"] for t in trades), 2),
    }

    # --- regime split ------------------------------------------------------
    by_reg = defaultdict(list)
    for t in trades:
        by_reg[t["regime"]].append(t)
    diag["regime_split"] = {k: _stats(v) for k, v in by_reg.items()}
    diag["current_regime"] = _regime_on(regimes, datetime.utcnow().date())

    # --- entry extension above the 20d MA ------------------------------------
    def _ext_bucket(e):
        if e is None:
            return "unknown"
        if e <= 5:
            return "<=5%"
        if e <= 8:
            return "5-8%"
        if e <= 12:
            return "8-12%"
        return ">12%"
    by_ext = defaultdict(list)
    for t in trades:
        by_ext[_ext_bucket(t["ext"])].append(t)
    diag["extension_vs_20d_ma"] = {k: _stats(v) for k, v in by_ext.items()}
    ext_risk_off = [t for t in trades if (t["ext"] or 0) > 5 and t["regime"] != "RISK-ON"]
    diag["extended_entries_outside_risk_on"] = _stats(ext_risk_off)

    # --- same-ticker re-entry churn --------------------------------------------
    by_ticker = defaultdict(list)
    for t in trades:
        by_ticker[t["ticker"]].append(t)
    reentries, spaced = [], []
    for tk, lst in by_ticker.items():
        lst.sort(key=lambda t: t["sell_date"])
        for i, t in enumerate(lst):
            prev_exit = lst[i - 1]["sell_date"] if i > 0 else None
            if prev_exit and (t["entry_date"] - prev_exit).days <= reentry_days:
                reentries.append(t)
            else:
                spaced.append(t)
    diag["reentry"] = {
        "definition": f"entry within {reentry_days} calendar days of the prior exit of the same ticker",
        "reentries": _stats(reentries),
        "spaced_entries": _stats(spaced),
        "reentry_list": [(t["ticker"], str(t["sell_date"]), round(t["pct"], 1)) for t in reentries],
    }

    # --- kill geometry -----------------------------------------------------------
    by_kill = defaultdict(list)
    for t in trades:
        by_kill[t["kill"]].append(t)
    diag["kill_kind"] = {k: dict(_stats(v), **{"avg_loser_pct": round(
        sum(x["pct"] for x in v if x["pct"] <= 0) / max(1, sum(1 for x in v if x["pct"] <= 0)), 2)})
        for k, v in by_kill.items()}

    # --- ranked leaks (dollars) ----------------------------------------------------
    leaks = []
    if reentries:
        leaks.append(("same-ticker re-entry within 3 days", _stats(reentries)["sum_usd"], _stats(reentries)["n"]))
    if ext_risk_off:
        leaks.append(("entries >5% above 20d MA outside RISK-ON", _stats(ext_risk_off)["sum_usd"], len(ext_risk_off)))
    for lab, v in by_reg.items():
        if lab != "RISK-ON":
            s = _stats(v)
            leaks.append((f"all entries in {lab} regime", s["sum_usd"], s["n"]))
    k20 = by_kill.get("20d-only", [])
    if k20:
        s = _stats([t for t in k20 if t["pct"] <= 0])
        if s["n"]:
            leaks.append(("losers whose only kill was '20d break' (unpriced)", s["sum_usd"], s["n"]))
    tail = [t for t in trades if t["pct"] <= -5]
    if tail:
        s = _stats(tail)
        leaks.append(("loss tail <= -5%", s["sum_usd"], s["n"]))
    leaks.sort(key=lambda x: x[1])
    diag["ranked_leaks_usd"] = [{"leak": a, "sum_usd": b, "n": c} for a, b, c in leaks if b < 0]
    return diag


def _fmt_stats(s):
    if not s or not s.get("n"):
        return "n=0"
    return f"n={s['n']} win {s['win_rate']:.0f}% avg {s['avg_pct']:+.2f}% ${s['sum_usd']:+.0f}"


def format_diagnostics(diag):
    """Compact, prompt-ready rendering (~1.2k chars)."""
    if not diag or diag.get("empty"):
        return ""
    p = diag.get("payoff", {})
    lines = [
        f"COMPUTED DIAGNOSTICS (all {diag['campaigns']} campaigns from {diag['closed_trades']} closed rows, last {diag['window_days']}d; "
        f"synced inventory excluded: n={diag['synced']['n']} ${diag['synced']['sum_usd']:+.0f}). These are population facts — they outrank any impression from a trade sample.",
        f"- Payoff: win rate {p.get('win_rate')}% | avg win {p.get('avg_win_pct'):+.2f}% (median {p.get('median_win_pct')}) | avg loss {p.get('avg_loss_pct'):+.2f}% (median {p.get('median_loss_pct')}) "
        f"| payoff {p.get('payoff_ratio')} → BREAKEVEN WIN RATE {p.get('breakeven_win_rate')}% | {p.get('winners_capped_3_to_5pct')}% of winners sit in the +2.5..+5.5% harvest band | net ${p.get('total_usd'):+.0f}",
        f"- Tail: worst {p.get('worst_5')} | best {p.get('best_3')}",
        "- Regime at ENTRY (SPY/NASDAQ vs 20d MA, NASDAQ 5d): " + " | ".join(f"{k}: {_fmt_stats(v)}" for k, v in sorted(diag['regime_split'].items())) + f" | regime now: {diag.get('current_regime')}",
        "- Entry extension above 20d MA (parsed from buy reason): " + " | ".join(f"{k}: {_fmt_stats(v)}" for k, v in sorted(diag['extension_vs_20d_ma'].items())),
        f"- Extended (>5% above 20d MA) entries outside RISK-ON: {_fmt_stats(diag.get('extended_entries_outside_risk_on'))}",
        f"- Re-entry ({diag['reentry']['definition']}): RE-ENTRIES {_fmt_stats(diag['reentry']['reentries'])} vs SPACED {_fmt_stats(diag['reentry']['spaced_entries'])}; list {diag['reentry']['reentry_list'][:8]}",
        "- Kill kind at entry: " + " | ".join(f"{k}: {_fmt_stats(v)} (avg loser {v.get('avg_loser_pct')}%)" for k, v in sorted(diag['kill_kind'].items())),
    ]
    if diag.get("ranked_leaks_usd"):
        lines.append("- RANKED LEAKS ($): " + "; ".join(f"{l['leak']} = ${l['sum_usd']:+.0f} over {l['n']}" for l in diag["ranked_leaks_usd"][:5]))
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    ch = sys.argv[1] if len(sys.argv) > 1 else "9ea09b9as"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    d = compute_trade_diagnostics(ch, days)
    print(format_diagnostics(d))
    print()
    print(json.dumps(d, default=str, indent=1)[:3000])
