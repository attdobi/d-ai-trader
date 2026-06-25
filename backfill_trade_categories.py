#!/usr/bin/env python3
"""One-time (idempotent) backfill: re-categorize existing trade_outcomes rows.

The previous outcome_category logic marked any trade within ±2% as
'break_even', so real -$6 to -$16 losses on small positions were labeled
break-even. That starved the feedback agent of loss signal. This script
recomputes every row's outcome_category with the dollar-delta rule in
feedback_agent.categorize_outcome.

Safe to run repeatedly: it only writes rows whose category actually changes,
and prints a before/after summary. It does NOT touch gain_loss_amount or
gain_loss_percentage (those were already stored correctly).

Usage:
    ./dai/bin/python backfill_trade_categories.py          # apply
    ./dai/bin/python backfill_trade_categories.py --dry-run # preview only
"""

import sys

from sqlalchemy import text

from config import engine
from feedback_agent import categorize_outcome


def main(dry_run=False):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, ticker, gain_loss_amount, gain_loss_percentage, outcome_category
            FROM trade_outcomes
            ORDER BY sell_timestamp DESC
        """)).fetchall()

    if not rows:
        print("No trade_outcomes rows found — nothing to backfill.")
        return

    changes = []
    for r in rows:
        new_cat = categorize_outcome(r.gain_loss_amount, r.gain_loss_percentage)
        if new_cat != r.outcome_category:
            changes.append((r.id, r.ticker, r.outcome_category, new_cat,
                            float(r.gain_loss_amount or 0), float(r.gain_loss_percentage or 0)))

    print(f"Scanned {len(rows)} rows; {len(changes)} need re-categorization.\n")
    if changes:
        print(f"{'TICKER':8} {'$':>9} {'%':>8}  {'OLD':>18} → {'NEW'}")
        for _id, ticker, old, new, amt, pct in changes:
            print(f"{ticker:8} {amt:9.2f} {pct*100:7.2f}%  {old:>18} → {new}")

    if dry_run:
        print("\n--dry-run: no changes written.")
        return

    if changes:
        with engine.begin() as conn:
            for _id, _t, _old, new, _a, _p in changes:
                conn.execute(
                    text("UPDATE trade_outcomes SET outcome_category = :c WHERE id = :id"),
                    {"c": new, "id": _id},
                )
        print(f"\n✅ Updated {len(changes)} rows.")
    else:
        print("✅ All rows already correctly categorized.")

    # Post-update distribution
    with engine.connect() as conn:
        dist = conn.execute(text("""
            SELECT outcome_category, COUNT(*) AS n
            FROM trade_outcomes
            GROUP BY outcome_category
            ORDER BY n DESC
        """)).fetchall()
    print("\nOutcome distribution now:")
    for d in dist:
        print(f"  {d.outcome_category:20} {d.n}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
