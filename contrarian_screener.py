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
  * A kill must be a genuinely evidenced support/invalidation price below entry and inside
    the active D cap. Candidate lines print price, 20d MA and a 3% downside reference;
    an above-entry MA is a reclaim level, and the reference does not authorize a stop.
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
import math
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo

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

_BENCHMARKS = ("SPY", "QQQ", "SMH")
_MARKET_TIMEZONE = ZoneInfo("America/New_York")


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


def _session_snapshot(bars, closes, session_date):
    """Use the current session's observed daily bar, which can be incomplete."""
    if len(closes) < 2 or closes.index[-1].date() != session_date:
        return {}
    try:
        bar = bars.loc[closes.index[-1]]
        opening, low, high = (float(bar[name]) for name in ("Open", "Low", "High"))
        price, previous = float(closes.iloc[-1]), float(closes.iloc[-2])
    except (KeyError, TypeError, ValueError):
        return {}
    if not all(math.isfinite(n) and n > 0 for n in (opening, low, high, price, previous)):
        return {}
    if not (low <= min(opening, price) <= max(opening, price) <= high and high > low):
        return {}
    from_low = (price / low - 1) * 100
    range_position = (price - low) / (high - low) * 100
    return {
        "session_date": session_date.isoformat(),
        "session_low": round(low, 4),
        "session_open": round(opening, 4),
        "session_high": round(high, 4),
        "session_from_low_pct": round(from_low, 2),
        "session_range_pct": round(range_position, 1),
        "session_day_pct": round((price / previous - 1) * 100, 2),
        "session_low_distance_pct": round((price - low) / price * 100, 3),
        "session_reclaim": low < opening <= price and from_low >= 0.5 and range_position >= 50,
    }


def _bench_stats(df, sym, multi, session_date):
    """{'price','vs20d','r5'} for a benchmark symbol in the batched download."""
    try:
        bars = df[sym] if multi else df
        closes = bars["Close"].dropna()
        if len(closes) < 21:
            return None
        price = float(closes.iloc[-1])
        sma20 = float(closes.iloc[-20:].mean())
        return {
            "price": price,
            "vs20d": (price / sma20 - 1) * 100 if sma20 else 0.0,
            "r5": (price / float(closes.iloc[-6]) - 1) * 100,
            "r20": (price / float(closes.iloc[-21]) - 1) * 100,
            **_session_snapshot(bars, closes, session_date),
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


def get_contrarian_candidates(limit=None, exclude=None, *, include_regime=False):
    """Return ranked non-extended front-run candidates (pull-backs / oversold reversals).

    `exclude`: tickers to drop (re-entry quarantine — names exited within the last 2
    sessions). Cached for DAI_CONTRARIAN_CACHE_MIN minutes so it doesn't re-download
    every cycle. Best-effort: any failure returns the last good cache (or []) so the
    decider never breaks.

    With include_regime, return (candidates, regime) from the same batch.
    """
    if limit is None:
        limit = int(os.getenv("DAI_CONTRARIAN_LIMIT", "10"))
    if os.getenv("DAI_CONTRARIAN_ENABLED", "1") not in ("1", "true", "True"):
        return ([], None) if include_regime else []
    excluded = {str(t).upper() for t in (exclude or []) if t}
    cache_min = float(os.getenv("DAI_CONTRARIAN_CACHE_MIN", "25"))
    now = time.time()
    session_date = datetime.fromtimestamp(now, _MARKET_TIMEZONE).date()

    def _finish(cands, *, stale=False):
        eligible = [c for c in cands if c["ticker"] not in excluded]
        if stale:
            # The legacy screen can fall back to cached candidates. Strip recovery
            # evidence so an old low cannot be presented as a current session low.
            eligible = [dict({k: v for k, v in c.items() if not k.startswith("session_")},
                             snapshot_stale=True) for c in eligible]
        elif (_CACHE["regime"] or {}).get("label") in ("RISK-OFF", "MIXED"):
            reversals = [c for c in eligible if c.get("session_reclaim")
                         and c.get("session_date") == session_date.isoformat()
                         and c["setup"] == "oversold-reversal"]
            reversals.sort(key=lambda c: (0 < c["session_low_distance_pct"] <= 1.3, c["score"]), reverse=True)
            priority = reversals[:2]
            prioritized = {c["ticker"] for c in priority}
            eligible = priority + [c for c in eligible if c["ticker"] not in prioritized]
        selected = eligible[:limit]
        if include_regime:
            return selected, None if stale else _CACHE["regime"]
        return selected

    if (_CACHE["regime"] and (now - _CACHE["ts"]) < cache_min * 60
            and datetime.fromtimestamp(_CACHE["ts"], _MARKET_TIMEZONE).date() == session_date):
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

        spy = _bench_stats(df, "SPY", multi, session_date)
        qqq = _bench_stats(df, "QQQ", multi, session_date)
        smh = _bench_stats(df, "SMH", multi, session_date)
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
                session = _session_snapshot(sub, closes, session_date)

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
                vols = sub["Volume"].dropna() if "Volume" in sub else ()
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
                # An oversold name can recover within the session while still red
                # versus yesterday. Require observed recovery for that path.
                elif rsi < 38 and month > -30 and (day > 0.0 or session.get("session_reclaim")):
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
                    **session,
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
            "label": label, "why": why, "spy": spy, "qqq": qqq, "smh": smh, "leaders": leader_stats,
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
        return _finish(_CACHE["data"], stale=True)


def get_index_regime():
    """Read the regime from the same fresh batch as the candidates."""
    _, regime = get_contrarian_candidates(include_regime=True)
    return regime


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
    recovery = []
    for key in ("spy", "qqq", "smh"):
        snapshot = regime.get(key) or {}
        if snapshot.get("session_date"):
            reclaim = "open reclaimed" if snapshot["session_reclaim"] else "reclaim unconfirmed"
            recovery.append(f"{key.upper()} {snapshot['session_day_pct']:+.2f}% vs prior close, "
                            f"+{snapshot['session_from_low_pct']:.2f}% off low, {reclaim} ({snapshot['session_date']})")
    recovery_text = " | ".join(recovery) or "unavailable"
    return (
        f"# INDEX REGIME: {regime['label']} ({regime['why']}) | {_b('SPY', regime.get('spy'))} | "
        f"{_b('QQQ', regime.get('qqq'))} | {lead_txt}\n"
        f"# SESSION RECOVERY (observed daily bars, may be incomplete): {recovery_text}\n"
        "# DEPLOYMENT RULE BY REGIME — RISK-ON: full rails, up to 3 new BUYs; extension ≤5% above 20d MA at full size, "
        "5-8% at half size. MIXED: at most 2 new BUYs at half size, extension ≤5% only. RISK-OFF: evaluate selective "
        "opportunities; at most 1 new BUY at half size, only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; "
        "no re-entry exceptions. Hold cash when independent candidate gates fail; never force a BUY. "
        "The regime never relaxes the priced-kill rule (K:<price>;D:<%>)."
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
        "# near the open. PRIORITIZE evaluating these over extended gainers. Each line prints PRICE, 20d MA, and a 3% downside reference.",
        "# A 20d MA ABOVE entry is a reclaim/resistance level, not a protective stop. Use it as K only when BELOW entry and supported as relevant support.",
        "# K must be a genuinely evidenced support/invalidation price BELOW entry. Compute positive D = (entry - K) / entry × 100.",
        "# The active D cap still applies. Without a justified below-entry K inside that cap, WATCH/PASS; do not force a BUY.",
        "# The printed 3% reference is not permission or an exception to the active cap. Never invent a tighter stop merely to pass the gate.",
        "# Session recovery can occur while the day is still red. A reclaim and the observed low are evidence to inspect, never an automatic stop or BUY.",
        "# A stale snapshot needs refreshed price and support evidence before entry.",
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
        if c.get("snapshot_stale"):
            tag += " | STALE SCREEN SNAPSHOT"
        if c.get("session_date"):
            reclaim = "open reclaimed" if c["session_reclaim"] else "reclaim unconfirmed"
            tag += (f" | session {c['session_date']}: low ${c['session_low']:.4f}, open ${c['session_open']:.4f}, "
                    f"high ${c['session_high']:.4f}, +{c['session_from_low_pct']:.2f}% off low, {reclaim}, "
                    f"distance to observed low {c['session_low_distance_pct']:.3f}%")
        price_text = (
            f"${c['price']:.2f} | 20d MA ${c['sma20']:.2f} | 3% reference ${c['kill_3pct']:.2f} | "
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
