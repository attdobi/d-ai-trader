#!/usr/bin/env python3
"""Quick probe to compare Schwab baseline vs shadow-ledger effective funds."""

import json
import sys

from schwab_client import get_portfolio_snapshot, schwab_client
from schwab_ledger import components, compute_effective_funds


def main() -> None:
    if not schwab_client.is_authenticated:
        if not schwab_client.authenticate():
            print("❌ Unable to authenticate with Schwab API.", file=sys.stderr)
            sys.exit(1)

    snapshot = get_portfolio_snapshot()
    if not snapshot:
        print("❌ Could not retrieve Schwab portfolio snapshot.", file=sys.stderr)
        sys.exit(1)

    baseline = snapshot.get("funds_available_explicit")
    if baseline is None:
        baseline = snapshot.get("funds_available_raw", 0.0)

    effective = compute_effective_funds(baseline)
    payload = {
        "baseline_funds": round(float(baseline), 2),
        "effective_funds": round(float(effective), 2),
        "ledger_components": components(),
        "open_orders_count": snapshot.get("open_orders_count", 0),
    }

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
