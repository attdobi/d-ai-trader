"""Contrarian / pull-back candidate screener + index-regime read.

The summarizer feeds the decider news + GAINERS — names that have ALREADY moved and
are therefore extended, which the anti-chase doctrine (correctly) rejects. That leaves
the decider with nothing to front-run and it sits in cash.

This module supplies the missing half: NON-extended, front-runnable candidates —
pull-backs inside an uptrend and oversold reversals turning up — screened purely with
yfinance/pandas (no LLM cost, same spirit as the momentum recap). The decider evaluates
these as BUY candidates whose thesis is the SETUP itself (support reclaim / reversal),
not a fresh news catalyst.

Lessons encoded 2026-09-02 (see agents/decider/MEMORY.default.md):
  * Extension above the 20d MA is the swing-timeframe chase metric. The old screen only
    capped the DAY move, so it happily served "pullbacks" 9-18% above the 20d MA
    (IONQ -10.4%, RKLB -7.2%, MRVL -9.1%, ORCL -5.0%). Candidates > DAI_CONTRARIAN_MAX_EXT
    (default 8%) above their 20d MA are dropped; 5-8% are tagged EXTENDED (half size,
    RISK-ON only).
  * The same rules made money while the index and the momentum leaders were above their
    20d MAs and lost in every bucket once the leaders rolled over, so the screener also
    publishes an INDEX REGIME line (SPY/QQQ vs 20d MA, 5d return, leader-cohort health).
  * A kill must be a price. Each candidate line prints the price, the 20d MA level and the
    3% kill so the decider can write K:<price>;D:<%> from supplied numbers.
  * Same-ticker re-entry within 3 days of an exit was the largest measured leak; callers
    pass `exclude=` (recently exited tickers) and the block prints a QUARANTINE line.

Public API:
    get_contrarian_candidates(limit=None, exclude=None) -> list[dict]
    get_index_regime() -> dict | None
    format_index_regime(regime) -> str                     # prompt-ready line(s)
    format_contrarian_watchlist(candidates, quarantined=None) -> str   # prompt-ready block
"""
import os
import time
import logging
import statistics

logger = logging.getLogger(__name__)

# Curated liquid, actively-traded US universe (~130 names across sectors). Kept modest
# so one batched yfinance download stays fast; env DAI_CONTRARIAN_UNIVERSE can override
# with a comma-separated list.
_DEFAULT_UNIVERSE = [
    # mega/large tech + semis
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "AVGO", "QCOM",
    "MU", "INTC", "TXN", "AMAT", "LRCX", "KLAC", "ARM", "SMCI", "MRVL", "ON",
    "ADI", "NXPI", "MCHP",
    # software / cloud / internet
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR", "CRWD", "PANW", "DDOG", "NET",
    "ZS", "SHOP", "TEAM", "WDAY", "MDB", "NFLX", "DIS", "CMCSA", "UBER", "ABNB",
    "DASH", "RBLX", "SPOT", "PINS", "SNAP",
    # financials / fintech
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "PYPL", "SOFI",
    "COIN", "AXP", "SCHW", "HOOD", "AFRM",
    # consumer / retail
    "WMT", "COST", "HD", "LOW", "NKE", "SBUX", "MCD", "TGT", "LULU", "CMG",
    "CVNA", "KO", "PEP", "PG",
    # autos / EV
    "F", "GM", "RIVN", "LCID", "NIO",
    # energy
    "XOM", "CVX", "COP", "SLB", "OXY", "MPC", "PSX", "DVN",
    # healthcare
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ISRG", "AMGN", "GILD",
    "MRNA", "CVS",
    # industrials / defense
    "BA", "CAT", "DE", "GE", "HON", "UNP", "LMT", "RTX", "GD", "NOC",
    # telecom / airlines
    "T", "VZ", "AAL", "DAL", "UAL", "LUV",
    # high-beta / popular trading names
    "GME", "AMC", "U", "CELH", "DKNG", "RKLB", "IONQ", "PLUG", "FSLR", "ENPH",
    "RUN", "CHPT", "AI", "SOUN",
]

_BENCHMARKS = ("SPY", "QQQ")


def _universe():
    raw = os.getenv("DAI_CONTRARIAN_UNIVERSE", "").strip()
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    return list(_DEFAULT_UNIVERSE)


def _rsi(closes, period=14):
    """Wilder's RSI on a list of closes."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


_CACHE = {"ts": 0.0, "data": [], "regime": None}


def _bench_stats(df, sym, multi):
    """{'price','vs20d','r5'} for a benchmark symbol in the batched download."""
    try:
        closes = (df[sym] if multi else df)["Close"].dropna()
        if len(closes) < 21:
            return None
        price = float(closes.iloc[-1])
        sma20 = float(closes.iloc[-20:].mean())
        return {
            "price": price,
            "vs20d": (price / sma20 - 1) * 100 if sma20 else 0.0,
            "r5": (price / float(closes.iloc[-6]) - 1) * 100,
            "r20": (price / float(closes.iloc[-21]) - 1) * 100,
        }
    except Exception:
        return None


def _regime_label(spy, qqq, leaders):
    """RISK-ON / MIXED / RISK-OFF from index position and momentum-leader health.

    RISK-OFF  : QQQ below its 20d MA, or QQQ 5d <= -2%, or SPY > 0.5% below its 20d MA,
                or the momentum-leader cohort is unwinding (median 5d <= -3% or fewer
                than half still above their 20d MA). The leader test is what catches a
                momentum unwind while SPY still sits marginally above its average
                (Aug 17-21, 2026: SPY +0.2..+2% vs 20d, leaders -5..-10%).
    RISK-ON   : SPY and QQQ above their 20d MA, QQQ 5d > -1%, leaders median 5d > -1.5%.
    MIXED     : everything else.
    """
    q = qqq or spy
    reasons = []
    if q and q["vs20d"] < 0:
        reasons.append("QQQ below 20d MA")
    if q and q["r5"] <= -2.0:
        reasons.append("QQQ 5d <= -2%")
    if spy and spy["vs20d"] < -0.5:
        reasons.append("SPY below 20d MA")
    if leaders and leaders["n"] >= 5:
        if leaders["median_5d"] <= -3.0:
            reasons.append(f"momentum leaders median 5d {leaders['median_5d']:+.1f}%")
        if leaders["share_above_20d"] < 0.5:
            reasons.append(f"only {leaders['share_above_20d']*100:.0f}% of leaders above 20d MA")
    if reasons:
        return "RISK-OFF", "; ".join(reasons)
    if (spy and spy["vs20d"] > 0 and q and q["vs20d"] > 0 and q["r5"] > -1.0
            and (not leaders or leaders["n"] < 5 or leaders["median_5d"] > -1.5)):
        return "RISK-ON", "indexes above 20d MA, leaders healthy"
    return "MIXED", "indexes/leaders not aligned"


def get_contrarian_candidates(limit=None, exclude=None):
    """Return ranked non-extended front-run candidates (pull-backs / oversold reversals).

    `exclude`: tickers to drop (re-entry quarantine — names exited within the last 2
    sessions). Cached for DAI_CONTRARIAN_CACHE_MIN minutes so it doesn't re-download
    every cycle. Best-effort: any failure returns the last good cache (or []) so the
    decider never breaks.
    """
    if limit is None:
        limit = int(os.getenv("DAI_CONTRARIAN_LIMIT", "10"))
    if os.getenv("DAI_CONTRARIAN_ENABLED", "1") not in ("1", "true", "True"):
        return []
    excluded = {str(t).upper() for t in (exclude or []) if t}

    def _finish(cands):
        return [c for c in cands if c["ticker"] not in excluded][:limit]

    cache_min = float(os.getenv("DAI_CONTRARIAN_CACHE_MIN", "25"))
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < cache_min * 60:
        return _finish(_CACHE["data"])

    universe = _universe()
    max_ext = float(os.getenv("DAI_CONTRARIAN_MAX_EXT", "8.0"))
    half_ext = float(os.getenv("DAI_CONTRARIAN_HALF_EXT", "5.0"))
    try:
        import yfinance as yf
        # SPY/QQQ ride along in the same batched download so relative strength and the
        # regime read cost no extra request; they are benchmarks only, never candidates.
        download_list = universe + [b for b in _BENCHMARKS if b not in universe]
        multi = len(download_list) > 1
        df = yf.download(
            download_list, period="3mo", interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=True,
        )

        spy = _bench_stats(df, "SPY", multi)
        qqq = _bench_stats(df, "QQQ", multi)
        spy_week = spy["r5"] if spy else None
        spy_month = spy["r20"] if spy else None

        candidates, leaders = [], []
        for tk in universe:
            try:
                sub = df[tk] if multi else df
                closes = sub["Close"].dropna()
                highs = sub["High"].dropna()
                if len(closes) < 25:
                    continue
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                c5 = float(closes.iloc[-6]) if len(closes) >= 6 else prev
                c20 = float(closes.iloc[-21]) if len(closes) >= 21 else float(closes.iloc[0])
                if price <= 0 or prev <= 0:
                    continue
                day = (price / prev - 1) * 100
                week = (price / c5 - 1) * 100
                month = (price / c20 - 1) * 100
                sma20 = float(closes.iloc[-20:].mean())
                dist_sma = (price / sma20 - 1) * 100 if sma20 else 0.0
                hi20 = float(highs.iloc[-20:].max())
                pullback = (hi20 - price) / hi20 * 100 if hi20 else 0.0
                rsi = _rsi([float(x) for x in closes.values])

                # Momentum-leader cohort: names that WERE leading a week ago (1mo return measured
                # 5 sessions back >= +15%). Defining leaders on today's 1mo return would drop the
                # names that just unwound out of the cohort and hide the unwind; this keeps them in.
                if len(closes) >= 26:
                    c25 = float(closes.iloc[-26])
                    month_lag = (c5 / c25 - 1) * 100 if c25 > 0 else 0.0
                    if month_lag >= 15.0:
                        leaders.append((week, price > sma20))

                # Relative strength vs SPY over the same 5d/20d windows (percentage points).
                rs5 = round(week - spy_week, 2) if spy_week is not None else None
                rs20 = round(month - spy_month, 2) if spy_month is not None else None

                # Relative volume vs the trailing 20-session average (participation).
                rel_volume = None
                vols = sub["Volume"].dropna()
                if len(vols) > 1:
                    latest_vol = float(vols.iloc[-1])
                    avg_vol = float(vols.iloc[-21:-1].mean()) if len(vols) > 20 else float(vols.iloc[:-1].mean())
                    if latest_vol > 0 and avg_vol > 0:
                        rel_volume = round(latest_vol / avg_vol, 2)

                # Skip EXTENDED names on BOTH timeframes: the day-move/RSI test catches
                # post-pop chases; the 20d-MA distance test catches the swing-timeframe
                # chase (a "-2% day" 12% above the 20d MA is an unwind's first leg).
                if day >= 4.0 or pullback < 2.0 or rsi > 70 or dist_sma > max_ext:
                    continue

                setup, score = None, 0.0
                # 1) Pull-back inside an uptrend, near/above a rising 20d MA.
                if month > 5 and day <= 1.5 and 2.5 <= pullback <= 16 and 38 <= rsi <= 63 and dist_sma > -7:
                    setup = "pullback-in-uptrend"
                    # Reward proximity to the 20d MA (a priced, near stop) instead of raw
                    # month return, which rewarded the most extended names.
                    score = (month - pullback + (60 - abs(rsi - 48))) - 3.0 * max(0.0, dist_sma)
                # 2) Oversold name turning up today.
                elif rsi < 38 and day > 0.0 and month > -30:
                    setup = "oversold-reversal"
                    score = (42 - rsi) + day * 2

                if not setup:
                    continue
                ext_tag = "EXTENDED" if dist_sma > half_ext else ""
                candidates.append({
                    "ticker": tk, "setup": setup, "score": round(score, 1),
                    "price": round(price, 2), "sma20": round(sma20, 2),
                    "kill_3pct": round(price * 0.97, 2),
                    "day": round(day, 2), "week": round(week, 2), "month": round(month, 2),
                    "rsi": round(rsi, 1),
                    "pullback_from_20d_high": round(pullback, 2),
                    "dist_from_20d_ma": round(dist_sma, 2),
                    "rs5_vs_spy": rs5, "rs20_vs_spy": rs20,
                    "rel_volume": rel_volume,
                    "ext_tag": ext_tag,
                })
            except Exception:
                continue

        leader_stats = None
        if leaders:
            leader_stats = {
                "n": len(leaders),
                "median_5d": round(statistics.median(w for w, _ in leaders), 2),
                "share_above_20d": round(sum(1 for _, above in leaders if above) / len(leaders), 2),
            }
        label, why = _regime_label(spy, qqq, leader_stats)
        regime = {
            "label": label, "why": why, "spy": spy, "qqq": qqq, "leaders": leader_stats,
            "as_of": time.strftime("%Y-%m-%d %H:%M"),
        }

        candidates.sort(key=lambda c: c["score"], reverse=True)
        _CACHE["ts"] = now
        _CACHE["data"] = candidates
        _CACHE["regime"] = regime
        logger.info("Contrarian screen: %d candidates from %d-name universe; regime %s (%s)",
                    len(candidates), len(universe), label, why)
        return _finish(candidates)
    except Exception as exc:
        logger.warning("Contrarian screen failed (%s); using cache", exc)
        return _finish(_CACHE["data"]) if _CACHE["data"] else []


def get_index_regime():
    """Latest regime read (computed alongside the screen; triggers a screen if cold)."""
    if _CACHE["regime"] is None or not _CACHE["data"]:
        get_contrarian_candidates()
    return _CACHE["regime"]


def format_index_regime(regime):
    """Prompt-ready INDEX REGIME block: the read plus the deployment rule per regime."""
    if not regime:
        return ""
    def _b(name, b):
        if not b:
            return f"{name} n/a"
        return f"{name} {b['vs20d']:+.1f}% vs 20d MA, 5d {b['r5']:+.1f}%"
    lead = regime.get("leaders")
    lead_txt = (
        f"momentum leaders (1mo ≥ +15%, n={lead['n']}): median 5d {lead['median_5d']:+.1f}%, "
        f"{lead['share_above_20d']*100:.0f}% still above their 20d MA"
        if lead else "momentum leaders: n/a"
    )
    return (
        f"# INDEX REGIME: {regime['label']} ({regime['why']}) | {_b('SPY', regime.get('spy'))} | "
        f"{_b('QQQ', regime.get('qqq'))} | {lead_txt}\n"
        "# DEPLOYMENT RULE BY REGIME — RISK-ON: full rails, up to 3 new BUYs; extension ≤5% above 20d MA at full size, "
        "5-8% at half size. MIXED: at most 2 new BUYs at half size, extension ≤5% only. RISK-OFF: cash is the correct "
        "default; at most 1 new BUY at half size, only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; "
        "no re-entry exceptions. The regime never relaxes the priced-kill rule (K:<price>;D:<%>)."
    )


def format_contrarian_watchlist(candidates, quarantined=None):
    """Render a prompt-ready block for the decider. Empty string when no candidates and nothing quarantined."""
    quarantined = sorted({str(t).upper() for t in (quarantined or []) if t})
    if not candidates and not quarantined:
        return ""
    lines = [
        "# CONTRARIAN WATCHLIST (front-run candidates — pulled back / oversold, NOT extended on either timeframe)",
        "# Screened for the reversal/pullback setups your doctrine targets, capped at 8% above the 20-day MA (the",
        "# swing-timeframe chase metric). For these names a fresh NEWS catalyst is NOT required — the SETUP is the",
        "# thesis (pullback into support within an uptrend, or an oversold turn). Confirm with what is reliable:",
        "# price holding/reclaiming its 20-day MA or recent support, a constructive multi-day/monthly trend, and",
        "# stabilizing relative strength. Do NOT require intraday VWAP/10m/1h — usually absent for pullbacks and",
        "# near the open. PRIORITIZE these for BUY over extended gainers. Each line prints the PRICE, the 20d MA",
        "# level and the 3% kill: your K: is the HIGHER of (20d MA, 3% kill) — write K:<price>;D:<%> from them.",
        "# EXTENDED = 5-8% above the 20d MA: half size and only in RISK-ON. Never buy a name on the QUARANTINE line.",
    ]
    for c in candidates:
        rs5, rs20 = c.get("rs5_vs_spy"), c.get("rs20_vs_spy")
        rs_text = (
            f"| RS/SPY 5d {rs5:+.1f} / 20d {rs20:+.1f} "
            if rs5 is not None and rs20 is not None else ""
        )
        rel_vol = c.get("rel_volume")
        vol_text = f" | rel-vol {rel_vol:.1f}× 20d-avg" if rel_vol else ""
        tag = f" | {c['ext_tag']}" if c.get("ext_tag") else ""
        price_text = (
            f"${c['price']:.2f} | 20d MA ${c['sma20']:.2f} | 3% kill ${c['kill_3pct']:.2f} | "
            if c.get("price") and c.get("sma20") else ""
        )
        lines.append(
            f"- {c['ticker']}: {c['setup']} | {price_text}day {c['day']:+.1f}% / wk {c['week']:+.1f}% / mo {c['month']:+.1f}% "
            f"{rs_text}| RSI {c['rsi']} | -{c['pullback_from_20d_high']:.1f}% from 20d high "
            f"| {c['dist_from_20d_ma']:+.1f}% vs 20d MA{vol_text}{tag}"
        )
    if quarantined:
        lines.append(
            "# QUARANTINE (exited within the last 2 sessions — NO re-entry this cycle, whatever the setup): "
            + ", ".join(quarantined)
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    cands = get_contrarian_candidates()
    print(f"{len(cands)} candidates:")
    print(json.dumps(cands, indent=2))
    print("\n--- regime ---\n")
    print(format_index_regime(get_index_regime()))
    print("\n--- prompt block ---\n")
    print(format_contrarian_watchlist(cands, quarantined=["ORCL"]))
