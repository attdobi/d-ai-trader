"""One-off operator step: tell the Decider that tickets are whole shares (maintenance version).

Adds one line under the Rails line of the Decider's user template:
whole shares only; a half-size ticket that buys no whole share sizes to exactly one share when
its price is within MAX, otherwise pass and say so. Pairs with the round-up in order_sizing.py.
Idempotent; `--dry-run` prints the change without writing.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ACTOR = "claude_code"
RAILS_LINE = "- Rails (per-buy, USD): MIN={min_buy}, TYPICAL={typical_buy_low}-{typical_buy_high}, MAX={max_buy}"
WHOLE_SHARE_LINE = ("- Whole shares only: amount_usd must cover at least one share at the quoted price. If half size "
                    "buys no whole share, size to exactly one share when its price is within MAX; otherwise pass and say so.")


def transform(fields: dict) -> dict:
    tpl = fields.get("user_prompt_template") or ""
    if WHOLE_SHARE_LINE in tpl or RAILS_LINE not in tpl:
        return fields
    fields["user_prompt_template"] = tpl.replace(RAILS_LINE, RAILS_LINE + "\n" + WHOLE_SHARE_LINE, 1)
    return fields


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-hash", default=os.environ.get("CURRENT_CONFIG_HASH"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.config_hash:
        print("pass --config-hash or set CURRENT_CONFIG_HASH"); return 2
    from config import engine, IS_MARGIN_ACCOUNT
    import prompt_manager
    from policy_graph.operator import maintenance_version
    res = maintenance_version(
        engine, args.config_hash, "DeciderAgent", transform,
        "v{n} Decider (maintenance, claude_code 2026-09-17) · whole-shares line under the rails: a half-size ticket that buys "
        "no whole share sizes to exactly one share within MAX, otherwise pass (DE 2026-09-17 skipped at $400 vs $677.57)",
        repo_root=REPO_ROOT, is_margin_account=bool(IS_MARGIN_ACCOUNT), activate=prompt_manager.set_active_prompt_version,
        actor=ACTOR, dry_run=args.dry_run)
    print("result:", res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
