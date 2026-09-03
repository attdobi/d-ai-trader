"""Version-level outcome windows for the policy graph (Phase 1).

`version_window(engine, config_hash, versions)` measures every listed policy version on
`trade_outcomes.created_at` — the clock the feedback agent stamps when a position closes — inside
the window during which that version was in force:

    start = the activation event that switched the agent TO this version
            (fallback: the row's created_at when no event was recorded — events start 2026-08-13)
    end   = the next activation event for the agent after `start` (fallback: the next row's
            created_at after `start`; None = still in force)

Rows whose `original_reason` is 'Schwab synced position' are excluded (positions the trader
never chose). A window is `measurable` once it holds >= MIN_CLOSED closed trades. The prior
window is the previous version's window (by start); `winrate_delta` is only reported when both
windows are measurable enough to compare. `lineage_window` widens the start to the nearest
non-weekly ancestor (`lineage_version`) so reminder-only versions inherit their policy's window.

`prompt_outcome_attribution.py` is intentionally NOT modified or imported (D14): its clock is
`sell_timestamp` and its boundaries are row created_at only; the tooltip states the difference.

stdlib + `sqlalchemy.text`; never imports config; config_hash is explicit.
"""
from __future__ import annotations

from datetime import date, datetime
from statistics import mean
from typing import Optional

from sqlalchemy import text

MIN_CLOSED = 5
SYNCED_REASON = "Schwab synced position"
CLOCK_LABEL = "trade_outcomes.created_at (PT)"


# ----------------------------------------------------------------------------- time helpers
def to_datetime(value) -> Optional[datetime]:
    """Naive datetime from a DB value (datetime, date, ISO string with ' ' or 'T', or None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return None


def iso(value) -> Optional[str]:
    dt = to_datetime(value)
    return dt.isoformat() if dt is not None else None


# ----------------------------------------------------------------------------- data access
def load_activation_events(engine, config_hash: str, agent_type: str) -> list:
    """prompt_activation_events for one agent, ascending by id."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, created_at, batch_id, from_version, to_version, action, actor, reason
            FROM prompt_activation_events
            WHERE config_hash = :h AND agent_type = :a
            ORDER BY id ASC
        """), {"h": config_hash, "a": agent_type}).fetchall()
    return [dict(r._mapping) for r in rows]


def load_closed_trades(engine, config_hash: str) -> list:
    """Closed trades the trader chose (synced positions excluded), ascending by created_at."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, created_at, gain_loss_percentage, gain_loss_amount, original_reason, ticker
            FROM trade_outcomes
            WHERE config_hash = :h
              AND (original_reason IS NULL OR original_reason != :synced)
        """), {"h": config_hash, "synced": SYNCED_REASON}).fetchall()
    out = []
    for r in rows:
        m = r._mapping
        dt = to_datetime(m.get("created_at"))
        if dt is None:
            continue
        out.append({
            "id": m.get("id"),
            "created_at": dt,
            "pct": float(m.get("gain_loss_percentage") or 0.0),
            "pnl": float(m.get("gain_loss_amount") or 0.0),
            "ticker": m.get("ticker"),
        })
    out.sort(key=lambda t: (t["created_at"], t["id"] or 0))
    return out


# ----------------------------------------------------------------------------- windows
def _stats(trades: list, start: Optional[datetime], end: Optional[datetime]) -> dict:
    if start is None:
        return {"n_closed": 0, "win_rate": None, "avg_pct": None, "total_pnl": None}
    sel = [t for t in trades if t["created_at"] >= start and (end is None or t["created_at"] < end)]
    n = len(sel)
    if n == 0:
        return {"n_closed": 0, "win_rate": None, "avg_pct": None, "total_pnl": 0.0}
    wins = sum(1 for t in sel if t["pct"] > 0)
    return {
        "n_closed": n,
        "win_rate": round(wins / n, 4),
        "avg_pct": round(mean(t["pct"] for t in sel), 4),
        "total_pnl": round(sum(t["pnl"] for t in sel), 2),
    }


def version_bounds(versions: list, events: list) -> dict:
    """{version: {"start", "end", "start_source", "activation_event_id"}} (datetimes, naive).

    `versions`: dicts with `version`, `created_at` (+ optional `is_active`).
    `events`: activation events for the agent (dicts with `id`, `created_at`, `to_version`)."""
    evs = []
    for e in events or []:
        dt = to_datetime(e.get("created_at"))
        if dt is None:
            continue
        evs.append({"id": e.get("id"), "created_at": dt, "to_version": e.get("to_version"),
                    "from_version": e.get("from_version")})
    evs.sort(key=lambda e: (e["created_at"], e["id"] or 0))
    rows = []
    for v in versions or []:
        dt = to_datetime(v.get("created_at"))
        rows.append({"version": int(v["version"]), "created_at": dt})
    out = {}
    for r in rows:
        n = r["version"]
        first = next((e for e in evs if e["to_version"] == n), None)
        if first is not None:
            start, source, ev_id = first["created_at"], "activation_event", first["id"]
        else:
            start, source, ev_id = r["created_at"], "row_created_at", None
        end = None
        if start is not None:
            nxt = next((e for e in evs if e["created_at"] > start and e["to_version"] != n), None)
            candidates = [nxt["created_at"]] if nxt is not None else []
            if first is None:
                # pre-event era (no activation recorded for this version): the next row's
                # creation implicitly ended it, unless an activation event came first
                later = [x["created_at"] for x in rows
                         if x["version"] != n and x["created_at"] is not None and x["created_at"] > start]
                if later:
                    candidates.append(min(later))
            if candidates:
                end = min(candidates)
        out[n] = {"start": start, "end": end, "start_source": source, "activation_event_id": ev_id}
    return out


def version_window(engine, config_hash: str, versions: list, *, agent_type: str = "DeciderAgent",
                   events: Optional[list] = None, trades: Optional[list] = None,
                   min_closed: int = MIN_CLOSED) -> dict:
    """{version: outcome dict} for every entry of `versions`.

    Each entry: {"version", "created_at", optional "lineage_version", optional "is_active"}.
    `events`/`trades` may be passed to avoid re-querying (service.list_versions does)."""
    if events is None:
        events = load_activation_events(engine, config_hash, agent_type)
    if trades is None:
        trades = load_closed_trades(engine, config_hash)
    bounds = version_bounds(versions, events)
    lineage = {int(v["version"]): v.get("lineage_version") for v in versions or []}
    ordered = sorted(bounds.items(), key=lambda kv: (kv[1]["start"] or datetime.min, kv[0]))
    # measured window per version: own window, widened back to the lineage version's start
    windows, applied = {}, {}
    for n, b in bounds.items():
        start, end = b["start"], b["end"]
        lin = lineage.get(n)
        win_start, lineage_applied = start, False
        if lin is not None and int(lin) != n and int(lin) in bounds:
            ls = bounds[int(lin)]["start"]
            if ls is not None and (win_start is None or ls < win_start):
                win_start = ls
                lineage_applied = True
        elif lin is not None and int(lin) == n:
            lineage_applied = True
        windows[n], applied[n] = (win_start, end), lineage_applied
    # prior window = the nearest earlier version (by start) that belongs to a DIFFERENT lineage —
    # a reminder-only follower is compared with the policy before its own, not with itself
    prior_of = {}
    for i, (n, _b) in enumerate(ordered):
        lin_n = lineage.get(n, n)
        prior = None
        for m, _mb in reversed(ordered[:i]):
            if lineage.get(m, m) != lin_n:
                prior = m
                break
        prior_of[n] = prior if prior is not None else (ordered[i - 1][0] if i > 0 else None)
    out = {}
    for n, b in bounds.items():
        start, end = b["start"], b["end"]
        lin = lineage.get(n)
        win_start, end = windows[n]
        lineage_applied = applied[n]
        cur = _stats(trades, win_start, end)
        p = prior_of.get(n)
        prior = _stats(trades, *windows[p]) if p is not None else _stats(trades, None, None)
        measurable = cur["n_closed"] >= min_closed
        delta = None
        if measurable and cur["win_rate"] is not None and prior["win_rate"] is not None:
            delta = round(cur["win_rate"] - prior["win_rate"], 4)
        out[n] = {
            **cur,
            "prior_win_rate": prior["win_rate"],
            "prior_n_closed": prior["n_closed"],
            "prior_version": p,
            "winrate_delta": delta,
            "measurable": measurable,
            "window": [iso(win_start), iso(end)],
            "own_window": [iso(start), iso(end)],
            "start_source": b["start_source"],
            "activation_event_id": b["activation_event_id"],
            "clock": CLOCK_LABEL,
            "lineage_window": lineage_applied,
            "lineage_version": (int(lin) if lin is not None else n),
        }
    return out


NO_ATTRIBUTION = {"outcome": None, "reason": "no direct trade attribution"}

__all__ = [
    "version_window", "version_bounds", "load_activation_events", "load_closed_trades",
    "to_datetime", "iso", "MIN_CLOSED", "SYNCED_REASON", "CLOCK_LABEL", "NO_ATTRIBUTION",
]
