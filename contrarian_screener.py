"""Contrarian / pull-back candidate screener.

The summarizer feeds the decider news + GAINERS — names that have ALREADY moved and
are therefore extended, which the anti-chase doctrine (correctly) rejects. That leaves
the decider with nothing to front-run and it sits in cash.

This module supplies the missing half: NON-extended, front-runnable candidates —
pull-backs inside an uptrend and oversold reversals turning up — screened purely with
yfinance/pandas (no LLM cost, same spirit as the momentum recap). The decider evaluates
these as BUY candidates whose thesis is the SETUP itself (support reclaim / reversal),
not a fresh news catalyst.

Public API:
    get_contrarian_candidates(limit=None) -> list[dict]
    format_contrarian_watchlist(candidates) -> str   # prompt-ready block
"""
import os
import time
import logging

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


_CACHE = {"ts": 0.0, "data": []}


def get_contrarian_candidates(limit=None):
    """Return ranked non-extended front-run candidates (pull-backs / oversold reversals).

    Cached for DAI_CONTRARIAN_CACHE_MIN minutes so it doesn't re-download every cycle.
    Best-effort: any failure returns the last good cache (or []) so the decider never breaks.
    """
    if limit is None:
        limit = int(os.getenv("DAI_CONTRARIAN_LIMIT", "10"))
    if os.getenv("DAI_CONTRARIAN_ENABLED", "1") not in ("1", "true", "True"):
        return []
    cache_min = float(os.getenv("DAI_CONTRARIAN_CACHE_MIN", "25"))
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < cache_min * 60:
        return _CACHE["data"][:limit]

    universe = _universe()
    try:
        import yfinance as yf
        df = yf.download(
            universe, period="3mo", interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=True,
        )
        candidates = []
        for tk in universe:
            try:
                sub = df[tk] if len(universe) > 1 else df
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

                # Skip EXTENDED names — the gainers feed already covers those and anti-chase
                # rejects them. We want the opposite: cooled-off, non-extended setups.
                if day >= 4.0 or pullback < 2.0 or rsi > 70:
                    continue

                setup, score = None, 0.0
                # 1) Pull-back inside an uptrend, near/above a rising 20d MA.
                if month > 5 and day <= 1.5 and 2.5 <= pullback <= 16 and 38 <= rsi <= 63 and dist_sma > -7:
                    setup = "pullback-in-uptrend"
                    score = month - pullback + (60 - abs(rsi - 48))
                # 2) Oversold name turning up today.
                elif rsi < 38 and day > 0.0 and month > -30:
                    setup = "oversold-reversal"
                    score = (42 - rsi) + day * 2

                if not setup:
                    continue
                candidates.append({
                    "ticker": tk, "setup": setup, "score": round(score, 1),
                    "day": round(day, 2), "week": round(week, 2), "month": round(month, 2),
                    "rsi": round(rsi, 1),
                    "pullback_from_20d_high": round(pullback, 2),
                    "dist_from_20d_ma": round(dist_sma, 2),
                })
            except Exception:
                continue

        candidates.sort(key=lambda c: c["score"], reverse=True)
        _CACHE["ts"] = now
        _CACHE["data"] = candidates
        logger.info("Contrarian screen: %d candidates from %d-name universe", len(candidates), len(universe))
        return candidates[:limit]
    except Exception as exc:
        logger.warning("Contrarian screen failed (%s); using cache", exc)
        return _CACHE["data"][:limit] if _CACHE["data"] else []


def format_contrarian_watchlist(candidates):
    """Render a prompt-ready block for the decider. Empty string when no candidates."""
    if not candidates:
        return ""
    lines = [
        "# CONTRARIAN WATCHLIST (front-run candidates — pulled back / oversold, NOT extended)",
        "# Screened for the reversal/pullback setups your doctrine targets. For these names a fresh",
        "# NEWS catalyst is NOT required — the SETUP is the thesis (pullback into support within an",
        "# uptrend, or an oversold turn). Require technical confirmation: price holding/reclaiming",
        "# support, a positive/turning 10m/1h, and stabilizing relative strength. PRIORITIZE these",
        "# for BUY over extended gainers; anti-chase does not apply because they have not popped.",
    ]
    for c in candidates:
        lines.append(
            f"- {c['ticker']}: {c['setup']} | day {c['day']:+.1f}% / wk {c['week']:+.1f}% / mo {c['month']:+.1f}% "
            f"| RSI {c['rsi']} | -{c['pullback_from_20d_high']:.1f}% from 20d high | {c['dist_from_20d_ma']:+.1f}% vs 20d MA"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    cands = get_contrarian_candidates()
    print(f"{len(cands)} candidates:")
    print(json.dumps(cands, indent=2))
    print("\n--- prompt block ---\n")
    print(format_contrarian_watchlist(cands))
