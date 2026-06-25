"""Attribute realized market outcomes to prompt versions.

This is the load-bearing piece for retiring the human from the prompt-evolution
loop: it lets us ask "did the version we shipped actually improve win rate?" and
eventually supervise the critic on that answer instead of on human approvals.

Attribution method (a deliberate, documented proxy):
  - A prompt version V for (agent_type, config_hash) is "active" from its
    created_at until the next version's created_at (or now, if it's the latest).
  - We measure trades whose SELL closed inside that window, and compare win rate
    + average return against the PRIOR version's window.
  - delta = winrate(V) - winrate(prior). Positive ⇒ the change helped.

Known limitations (surface these, don't hide them):
  - Close-time attribution is approximate; entries made under V may close under
    V+1. It's the best signal available from trade_outcomes alone.
  - Most meaningful for DeciderAgent (it makes the trade calls). Summarizer/
    Feedback changes act indirectly.
  - Needs a minimum sample to be more than noise (see MIN_TRADES_FOR_SIGNAL).
  - Only ACTIVATED versions get measured. The critic's rejections are
    counterfactual — we can score the precision of its approvals, not its
    rejections, against the market.
"""

from statistics import mean

from sqlalchemy import text

from config import engine

MIN_TRADES_FOR_SIGNAL = 5  # below this, a window's win rate is treated as not-yet-measurable


def version_active_window(conn, agent_type, config_hash, version):
    """Return (start, end, prior_start) datetimes for a version's active window.

    end is None when the version is the most recent (still active).
    prior_start is None when there is no earlier version.
    """
    rows = conn.execute(text("""
        SELECT version, created_at
        FROM prompt_versions
        WHERE agent_type = :a AND config_hash = :h
        ORDER BY created_at ASC, version ASC
    """), {"a": agent_type, "h": config_hash}).fetchall()
    if not rows:
        return None, None, None

    idx = next((i for i, r in enumerate(rows) if r.version == version), None)
    if idx is None:
        return None, None, None

    start = rows[idx].created_at
    end = rows[idx + 1].created_at if idx + 1 < len(rows) else None
    prior_start = rows[idx - 1].created_at if idx - 1 >= 0 else None
    return start, end, prior_start


def window_performance(conn, config_hash, start, end):
    """Win rate + average return for trades CLOSED in [start, end)."""
    if start is None:
        return {"n": 0, "win_rate": None, "avg_pct": None, "total_pnl": 0.0}
    rows = conn.execute(text("""
        SELECT gain_loss_percentage, gain_loss_amount
        FROM trade_outcomes
        WHERE config_hash = :h
          AND sell_timestamp >= :start
          AND (:end IS NULL OR sell_timestamp < :end)
          AND ticker != 'N/A'
    """), {"h": config_hash, "start": start, "end": end}).fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_pct": None, "total_pnl": 0.0}
    wins = sum(1 for r in rows if float(r.gain_loss_percentage or 0) > 0)
    return {
        "n": n,
        "win_rate": wins / n,
        "avg_pct": mean(float(r.gain_loss_percentage or 0) for r in rows),
        "total_pnl": sum(float(r.gain_loss_amount or 0) for r in rows),
    }


def compute_version_outcome(conn, agent_type, config_hash, version):
    """Compare a version's window to the prior version's window.

    Returns a dict with both windows, the win-rate delta, and a `measurable`
    flag (True once the version's window has enough closed trades).
    """
    start, end, prior_start = version_active_window(conn, agent_type, config_hash, version)
    if start is None:
        return None
    cur = window_performance(conn, config_hash, start, end)
    prior = window_performance(conn, config_hash, prior_start, start)
    measurable = cur["n"] >= MIN_TRADES_FOR_SIGNAL
    winrate_delta = None
    if measurable and cur["win_rate"] is not None and prior["win_rate"] is not None:
        winrate_delta = cur["win_rate"] - prior["win_rate"]
    return {
        "agent_type": agent_type,
        "version": version,
        "current": cur,
        "prior": prior,
        "winrate_delta": winrate_delta,
        "realized_pnl": cur["total_pnl"],
        "measurable": measurable,
    }


def critic_vs_market(critic_verdict, winrate_delta):
    """Did the critic's verdict agree with what the market said?

    Only defined for activated versions (critic typically 'approve'). A positive
    delta means the shipped change helped; we count the critic 'right' if it
    approved a helping change. Returns True/False/None (None = not yet judgeable).
    """
    if winrate_delta is None or not critic_verdict:
        return None
    helped = winrate_delta > 0
    if critic_verdict == "approve":
        return helped
    if critic_verdict == "reject":
        return not helped  # human overrode a critic reject; market judges the critic
    return None
