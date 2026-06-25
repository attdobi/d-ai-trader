#!/usr/bin/env python3
"""Backfill realized market outcomes into prompt_change_reviews.

For every review row that was activated (to_version set) and whose version
window now has enough closed trades, compute the win-rate delta vs the prior
version and write realized_winrate_delta / realized_pnl / outcome_measured_at.

Idempotent and safe to run on a schedule (e.g. alongside the weekly feedback
job). Rows whose windows haven't matured are left pending. Run it after trades
have closed under a new version.

Usage:
    ./dai/bin/python backfill_version_outcomes.py            # apply
    ./dai/bin/python backfill_version_outcomes.py --dry-run  # preview
"""

import sys

from sqlalchemy import text

from config import engine
from prompt_outcome_attribution import compute_version_outcome


def main(dry_run=False):
    with engine.connect() as conn:
        reviews = conn.execute(text("""
            SELECT id, agent_type, config_hash, to_version
            FROM prompt_change_reviews
            WHERE to_version IS NOT NULL
              AND human_verdict = 'approve'
              AND realized_winrate_delta IS NULL
            ORDER BY created_at ASC
        """)).fetchall()

    if not reviews:
        print("No activated reviews awaiting outcome measurement.")
        return

    updates = []
    for r in reviews:
        with engine.connect() as conn:
            outcome = compute_version_outcome(conn, r.agent_type, r.config_hash, r.to_version)
        if not outcome or not outcome["measurable"]:
            continue
        updates.append((r.id, r.agent_type, r.to_version,
                        outcome["winrate_delta"], outcome["realized_pnl"],
                        outcome["current"]["n"]))

    print(f"{len(reviews)} activated review(s) pending; {len(updates)} now measurable.\n")
    for _id, agent, ver, delta, pnl, n in updates:
        d = f"{delta:+.1%}" if delta is not None else "n/a"
        print(f"  review #{_id}  {agent} v{ver}  Δwin={d}  pnl=${pnl:+.2f}  ({n} trades)")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    if updates:
        with engine.begin() as conn:
            for _id, _a, _v, delta, pnl, _n in updates:
                conn.execute(text("""
                    UPDATE prompt_change_reviews
                    SET realized_winrate_delta = :d,
                        realized_pnl = :p,
                        outcome_measured_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"d": delta, "p": pnl, "id": _id})
        print(f"\n✅ Wrote outcomes for {len(updates)} review(s).")
    else:
        print("No matured windows yet — re-run after more trades close.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
