#!/usr/bin/env python3
"""Reconcile stored trade_decisions against ACTUAL Schwab order outcomes.

READ-ONLY against Schwab (places/cancels nothing). For each recent Schwab order
it finds the matching decision row (by ticker + buy/sell + date + shares) and
writes the real execution_status (filled / rejected / canceled / expired) plus
the actual fill, so the dashboard and the feedback agent stop treating
rejected/canceled orders as trades.

Idempotent. Run after a session, or any time the dashboard looks out of sync
with the broker.

Usage:
    ./dai/bin/python reconcile_executions.py [DAYS] [--dry-run]
    ./dai/bin/python reconcile_executions.py 7 --dry-run
"""

import sys
import json
from datetime import datetime, timedelta

from sqlalchemy import text

from config import engine
from schwab_client import schwab_client, SchwabAPIClient


def _order_rows(days):
    """Return [(enteredDate, instruction, symbol, qty, status, fills)] from Schwab."""
    if not schwab_client.authenticate():
        print("❌ Could not authenticate to Schwab.")
        return []
    acc = schwab_client.account_hash
    resp = schwab_client.client.get_orders_for_account(
        acc,
        from_entered_datetime=datetime.utcnow() - timedelta(days=days),
        to_entered_datetime=datetime.utcnow(),
    )
    orders = resp.json() if resp.status_code == 200 else []
    out = []
    for o in orders:
        leg = (o.get("orderLegCollection") or [{}])[0]
        sym = (leg.get("instrument") or {}).get("symbol")
        instr = (leg.get("instruction") or "").upper()
        action = "buy" if "BUY" in instr else ("sell" if "SELL" in instr else None)
        if not sym or not action:
            continue
        qty, avg, amt = SchwabAPIClient._extract_fills(o)
        out.append({
            "date": (o.get("enteredTime") or "")[:10],
            "action": action,
            "ticker": sym.upper(),
            "qty": float(leg.get("quantity") or o.get("quantity") or 0),
            "status": (o.get("status") or "").upper(),
            "order_id": o.get("orderId"),
            "filled_qty": qty,
            "avg_price": avg,
            "filled_amount": amt,
        })
    return out


_STATUS_MAP = {
    "FILLED": "filled", "REJECTED": "rejected", "CANCELED": "canceled",
    "EXPIRED": "expired", "REPLACED": "canceled",
}


def main(days=7, dry_run=False):
    orders = _order_rows(days)
    if not orders:
        print("No Schwab orders to reconcile.")
        return
    print(f"Fetched {len(orders)} Schwab orders over {days}d.\n")

    cutoff = datetime.utcnow() - timedelta(days=days + 2)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, timestamp, data FROM trade_decisions
            WHERE timestamp >= :cutoff ORDER BY timestamp DESC
        """), {"cutoff": cutoff}).fetchall()

    used_order_ids = set()  # each Schwab order maps to at most ONE decision
    updates = []  # (row_id, new_data)
    for r in rows:  # newest first
        data = r.data if isinstance(r.data, list) else json.loads(r.data)
        if not isinstance(data, list):
            continue
        changed = False
        for d in data:
            if not isinstance(d, dict):
                continue
            action = str(d.get("action", "")).lower()
            if action not in ("buy", "sell") or d.get("execution_status") in _STATUS_MAP.values():
                continue
            tic = str(d.get("ticker", "")).upper()
            shares = float(d.get("shares") or 0)
            # Match a not-yet-consumed Schwab order: same ticker+action, qty within 1.
            match = None
            for o in orders:
                if o["order_id"] in used_order_ids:
                    continue
                if o["ticker"] != tic or o["action"] != action:
                    continue
                if shares and abs(o["qty"] - shares) > 1.01:
                    continue
                match = o
                break
            if not match:
                continue
            used_order_ids.add(match["order_id"])
            new_status = _STATUS_MAP.get(match["status"])
            if not new_status:
                continue
            d["execution_status"] = new_status
            d["order_id"] = match["order_id"]
            if new_status == "filled" and match["filled_amount"] is not None:
                d["executed_shares"] = match["filled_qty"]
                d["executed_price"] = match["avg_price"]
                d["executed_amount"] = round(match["filled_amount"], 2)
            changed = True
            print(f"  row#{r.id} {action.upper()} {tic} {shares}sh → {new_status} (order {match['order_id']})")
        if changed:
            updates.append((r.id, json.dumps(data)))

    print(f"\n{len(updates)} decision row(s) to update.")
    if dry_run:
        print("--dry-run: nothing written.")
        return
    if updates:
        with engine.begin() as conn:
            for rid, payload in updates:
                conn.execute(text("UPDATE trade_decisions SET data = :d WHERE id = :id"),
                             {"d": payload, "id": rid})
        print(f"✅ Updated {len(updates)} row(s).")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    days = int(args[0]) if args else 7
    main(days=days, dry_run="--dry-run" in sys.argv)
