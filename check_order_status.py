#!/usr/bin/env python3
"""READ-ONLY Schwab order diagnostic. Places NO orders, cancels nothing.

Confirms whether recent orders actually FILLED or are sitting WORKING/REJECTED —
the root of "live trading cut off / I hold no shares despite executed logs".

Usage:
    ./dai/bin/python check_order_status.py [ORDER_ID]
    ./dai/bin/python check_order_status.py 1006912187453
"""

import sys
import json
from datetime import datetime, timedelta

from schwab_client import schwab_client


def _fmt_executions(order):
    """Pull actual fills out of a Schwab order object."""
    legs = order.get("orderActivityCollection") or []
    fills = []
    for act in legs:
        for ex in act.get("executionLegs") or []:
            fills.append({
                "qty": ex.get("quantity"),
                "price": ex.get("price"),
                "time": ex.get("time"),
            })
    return fills


def summarize(order):
    status = (order.get("status") or "").upper()
    qty = order.get("quantity")
    filled = order.get("filledQuantity")
    remaining = order.get("remainingQuantity")
    leg = (order.get("orderLegCollection") or [{}])[0]
    sym = (leg.get("instrument") or {}).get("symbol")
    instr = leg.get("instruction")
    fills = _fmt_executions(order)
    avg_price = None
    filled_amt = None
    if fills:
        tot_qty = sum((f["qty"] or 0) for f in fills)
        tot_val = sum((f["qty"] or 0) * (f["price"] or 0) for f in fills)
        if tot_qty:
            avg_price = tot_val / tot_qty
            filled_amt = tot_val
    print(f"  {instr or '?':4} {sym or '?':8} status={status:18} "
          f"qty={qty} filled={filled} remaining={remaining}")
    if fills:
        print(f"     FILLED: {sum((f['qty'] or 0) for f in fills)} sh @ avg ${avg_price:.4f} = ${filled_amt:.2f}")
    else:
        print(f"     NO FILLS — order never executed against the account")
    return status


def main():
    if not schwab_client.authenticate():
        print("❌ Could not authenticate to Schwab.")
        return
    acc = schwab_client.account_hash

    order_id = sys.argv[1] if len(sys.argv) > 1 else "1006912187453"
    print(f"\n=== Order {order_id} ===")
    raw = schwab_client.get_order_status(order_id)
    if raw:
        summarize(raw)
    else:
        print("  (could not retrieve this order — may be too old or wrong account)")

    # Best-effort: list recent orders to see the fill pattern across the last week.
    print("\n=== Recent orders (last 7 days) ===")
    try:
        from_dt = datetime.utcnow() - timedelta(days=7)
        to_dt = datetime.utcnow()
        resp = schwab_client.client.get_orders_for_account(
            acc, from_entered_datetime=from_dt, to_entered_datetime=to_dt
        )
        orders = resp.json() if resp.status_code == 200 else []
        if not orders:
            print("  (no orders returned)")
        # newest first
        for o in sorted(orders, key=lambda x: x.get("enteredTime", ""), reverse=True)[:25]:
            ts = o.get("enteredTime", "")[:19]
            print(f"[{ts}] id={o.get('orderId')}")
            summarize(o)
        # tally
        from collections import Counter
        tally = Counter((o.get("status") or "").upper() for o in orders)
        print("\n  Status tally (7d):", dict(tally))
    except Exception as exc:
        print(f"  (could not list recent orders: {exc})")
        print("  Check open/working orders directly in the Schwab app.")


if __name__ == "__main__":
    main()
