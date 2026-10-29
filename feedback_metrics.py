"""Read-only, scoped metrics for the Feedback dashboard's nested windows.

The ledger writes naive UTC sale timestamps. Each counted item is a recorded
closed-outcome row, which may be a lot/partial closure rather than a distinct
purchase or round trip. No guessed deduplication or outcome recategorization is
performed here, and no model, broker or policy module is imported.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from collections.abc import Mapping

from sqlalchemy import text


def finite_number(value):
    """A missing/invalid value is unknown, not zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _finite_sum(values):
    if any(value is None for value in values):
        return None
    try:
        return finite_number(math.fsum(values))
    except OverflowError:
        return None


def _mapping(row):
    return row if isinstance(row, Mapping) else row._mapping


def is_recorded_closure(row):
    """Exclude explicit no-trade placeholders, preserving missing reasons."""
    row = _mapping(row)
    ticker = str(row.get("ticker") or "").strip()
    return bool(ticker and ticker.upper() != "N/A"
                and "market is closed" not in str(row.get("original_reason") or "").lower())


def is_scored_closure(row):
    """Eligibility for historical percentage win rate / mean-return metrics."""
    row = _mapping(row)
    return is_recorded_closure(row) and finite_number(row.get("gain_loss_percentage")) is not None


def utc_instant(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("A UTC timestamp is required")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso_utc(value):
    return utc_instant(value).isoformat().replace("+00:00", "Z")


def summarize_closures(rows, *, start, end, days):
    """Summarize an exact inclusive UTC interval without inventing no-data scores."""
    start, end = utc_instant(start), utc_instant(end)
    candidates = []
    for raw in rows:
        row = _mapping(raw)
        if not is_recorded_closure(row):
            continue
        if row.get("sell_timestamp") is None:
            continue
        try:
            stamp = utc_instant(row.get("sell_timestamp"))
        except (TypeError, ValueError, OverflowError):
            continue
        if start <= stamp <= end:
            candidates.append((row, stamp))
    eligible = [(row, stamp) for row, stamp in candidates if is_scored_closure(row)]
    returns = [finite_number(row["gain_loss_percentage"]) for row, _ in eligible]
    amounts = [finite_number(row.get("gain_loss_amount")) for row, _ in eligible]
    total = len(eligible)
    wins = sum(value > 0 for value in returns)
    losses = sum(value < 0 for value in returns)
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "flat_trades": total - wins - losses,
        "closed_outcome_rows": len(candidates),
        "unscored_trades": len(candidates) - total,
        "success_rate": wins / total if total else None,
        "avg_profit": math.fsum(value / total for value in returns) if total else None,
        "net_gain_dollars": _finite_sum(amounts) if total else None,
        "first_close_at": iso_utc(min(stamp for _, stamp in eligible)) if total else None,
        "last_close_at": iso_utc(max(stamp for _, stamp in eligible)) if total else None,
        "window": {"start": iso_utc(start), "end": iso_utc(end), "timezone": "UTC", "days": days,
                   "kind": "rolling_elapsed_days", "start_inclusive": True, "end_inclusive": True},
        "counting_unit": "closed_outcome_row",
        "success_definition": "positive_recorded_return",
        "average_definition": "unweighted_mean_recorded_return",
    }


def dashboard_period_metrics(engine, config_hash, periods, *, as_of=None):
    """One bounded SELECT supplies all windows with one scope and cutoff instant."""
    periods = sorted(set(periods))
    if not periods or any(type(days) is not int or not 1 <= days <= 1095 for days in periods):
        raise ValueError("Choose lookback windows from 1 to 1095 days")
    end = utc_instant(as_of)
    start = end - timedelta(days=max(periods))
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, original_reason
            FROM trade_outcomes
            WHERE config_hash = :config_hash
              AND sell_timestamp >= :start AND sell_timestamp <= :end
            ORDER BY sell_timestamp, id
        """), {"config_hash": config_hash, "start": start.replace(tzinfo=None),
               "end": end.replace(tzinfo=None)}).mappings().all()
    return {f"{days}d": summarize_closures(rows, start=end-timedelta(days=days), end=end, days=days)
            for days in periods}
