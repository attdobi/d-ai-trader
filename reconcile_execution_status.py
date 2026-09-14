#!/usr/bin/env python3
"""Reconcile buy/sell decisions against Schwab's order history (the broker is ground truth).

For 30 days no execution outcome was written back to trade_decisions (run_id was never passed
to the persister), so the Trades tab inferred fills from the local ledger — wrong in both
directions. This stamps every buy/sell decision inside Schwab's 60-day order window:

  * matched FILLED order          → execution_status=filled + executed shares/price/amount, order_id
  * matched REJECTED/CANCELED/…   → that status + Schwab's statusDescription
  * no order within the window    → execution_status=not_executed ("no matching Schwab order")

Decisions already carrying a broker-confirmed fill (status filled + order_id) or a
market_closed marker (never sent) are left alone. Also lists trade_outcomes rows with no
matching FILLED sell at the broker — phantom sales booked by the old sell path — for review
(never deleted here).

Dry-run by default; pass --apply to write.

    ./dai/bin/python reconcile_execution_status.py [--apply] [--config-hash H] [--days 59]
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import pytz
from sqlalchemy import text

from config import engine

PT = pytz.timezone("US/Pacific")
WINDOW_BEFORE = timedelta(minutes=3)   # decisions are stored just before orders go out
WINDOW_AFTER = timedelta(minutes=25)   # …and the cycle's execution stage takes a few minutes
CONFIRMED_STATUSES = {"filled"}
NOT_SENT_STATUSES = {"market_closed"}


def fetch_orders(days):
    from schwab_client import schwab_client
    if not schwab_client.ensure_authenticated():
        raise SystemExit("Schwab authentication failed — refresh the token first")
    now = datetime.now(timezone.utc)
    resp = schwab_client.client.get_orders_for_all_linked_accounts(
        from_entered_datetime=now - timedelta(days=days), to_entered_datetime=now + timedelta(hours=1)
    )
    resp.raise_for_status()
    orders = []
    for o in resp.json():
        legs = o.get("orderLegCollection") or []
        if not legs:
            continue
        leg = legs[0]
        instr = (leg.get("instruction") or "").upper()
        action = "buy" if instr.startswith("BUY") else "sell" if instr.startswith("SELL") else None
        if not action:
            continue
        entered = datetime.fromisoformat(str(o.get("enteredTime")).replace("+0000", "+00:00"))
        qty = notional = 0.0
        for act in o.get("orderActivityCollection") or []:
            for el in act.get("executionLegs") or []:
                q = float(el.get("quantity") or 0)
                p = float(el.get("price") or 0)
                qty += q
                notional += q * p
        orders.append({
            "id": str(o.get("orderId")),
            "symbol": (leg.get("instrument") or {}).get("symbol"),
            "action": action,
            "status": str(o.get("status") or "").upper(),
            "description": o.get("statusDescription") or "",
            "entered": entered,
            "filled_qty": float(o.get("filledQuantity") or qty or 0),
            "avg_price": (notional / qty) if qty else None,
            "amount": round(notional, 2) if qty else None,
            "used": False,
        })
    return orders


def to_utc(naive_pt):
    return PT.localize(naive_pt).astimezone(timezone.utc)


def nearest_order(orders, symbol, action, when_utc):
    best, best_dt = None, None
    for o in orders:
        if o["used"] or o["symbol"] != symbol or o["action"] != action:
            continue
        if not (when_utc - WINDOW_BEFORE <= o["entered"] <= when_utc + WINDOW_AFTER):
            continue
        dt = abs((o["entered"] - when_utc).total_seconds())
        if best is None or dt < best_dt:
            best, best_dt = o, dt
    return best


def reconcile(config_hash, days, apply):
    orders = fetch_orders(days)
    print(f"Schwab orders in the last {days} days: {len(orders)}")
    since = datetime.now() - timedelta(days=days)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, run_id, timestamp, data FROM trade_decisions
            WHERE config_hash = :h AND timestamp >= :since ORDER BY timestamp
        """), {"h": config_hash, "since": since}).fetchall()

    stats = {"filled": 0, "rejected": 0, "not_executed": 0, "left_alone": 0}
    updates = []
    offsets = []  # seconds from decision storage to order entry, for matched orders
    for row in rows:
        data = row.data if isinstance(row.data, list) else json.loads(row.data)
        when = to_utc(row.timestamp)
        changed = False
        for d in data:
            if not isinstance(d, dict) or d.get("kind"):
                continue
            action = str(d.get("action") or "").lower()
            if action not in ("buy", "sell"):
                continue
            st = str(d.get("execution_status") or "").lower()
            if (st in CONFIRMED_STATUSES and d.get("order_id")) or st in NOT_SENT_STATUSES:
                stats["left_alone"] += 1
                continue
            symbol = str(d.get("ticker") or "").upper()
            o = nearest_order(orders, symbol, action, when)
            if o is not None:
                o["used"] = True
                offsets.append((o["entered"] - when).total_seconds())
                if o["status"] == "FILLED" or o["filled_qty"] > 0:
                    d.update({
                        "execution_status": "filled", "order_id": o["id"],
                        "executed_shares": o["filled_qty"],
                        "executed_price": round(o["avg_price"], 4) if o["avg_price"] else d.get("executed_price"),
                        "executed_amount": o["amount"],
                        "execution_source": "broker_reconcile",
                    })
                    d.pop("execution_error", None)
                    stats["filled"] += 1
                else:
                    d.update({
                        "execution_status": o["status"].lower() or "rejected", "order_id": o["id"],
                        "execution_error": o["description"] or f"Schwab order status {o['status']}",
                        "execution_source": "broker_reconcile",
                    })
                    stats["rejected"] += 1
                changed = True
            elif not st:
                d.update({
                    "execution_status": "not_executed",
                    "execution_error": f"No matching Schwab {action.upper()} order within {int(WINDOW_AFTER.total_seconds()//60)} min "
                                       f"of this cycle (reconciled from broker order history)",
                    "execution_source": "broker_reconcile",
                })
                stats["not_executed"] += 1
                changed = True
            else:
                stats["left_alone"] += 1   # already stamped failed/skipped/… and no order: consistent
        if changed:
            updates.append((row.id, data))

    print(f"decisions → filled {stats['filled']}, rejected {stats['rejected']}, "
          f"not_executed {stats['not_executed']}, left alone {stats['left_alone']}; rows to update: {len(updates)}")
    if offsets:
        offsets.sort()
        print(f"matched-order offsets (decision stored → order entered): min {offsets[0]:.0f}s, "
              f"median {offsets[len(offsets)//2]:.0f}s, max {offsets[-1]:.0f}s (window −{int(WINDOW_BEFORE.total_seconds())}s…+{int(WINDOW_AFTER.total_seconds())}s)")
    orphans = [o for o in orders if not o["used"] and (o["status"] == "FILLED" or o["filled_qty"] > 0)]
    if orphans:
        print(f"⚠️  {len(orphans)} FILLED broker order(s) matched NO decision (manual trades, or a window miss):")
        for o in orphans[:12]:
            print(f"   {o['entered'].astimezone(PT).strftime('%m/%d %H:%M PT')} {o['symbol']} {o['action'].upper()} "
                  f"{o['filled_qty']:g} sh @ {o['avg_price'] or 0:.2f}")
    if apply and updates:
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"trade_decisions_reconcile_{datetime.now():%Y%m%d_%H%M%S}.json")
        with engine.connect() as conn:
            originals = conn.execute(text("SELECT id, data FROM trade_decisions WHERE id = ANY(:ids)"),
                                     {"ids": [rid for rid, _ in updates]}).fetchall()
        with open(backup_path, "w") as fh:
            json.dump({str(r.id): (r.data if isinstance(r.data, list) else json.loads(r.data)) for r in originals}, fh)
        print(f"🗄️  backup of {len(originals)} original rows: {backup_path}")
        with engine.begin() as conn:
            for rid, data in updates:
                conn.execute(text("UPDATE trade_decisions SET data = :d WHERE id = :id"),
                             {"d": json.dumps(data), "id": rid})
        print(f"✅ wrote {len(updates)} trade_decisions rows")
    elif updates:
        print("(dry run — pass --apply to write)")

    # Phantom sell outcomes: a sell the ledger booked with no FILLED sell at the broker.
    with engine.connect() as conn:
        outs = conn.execute(text("""
            SELECT id, ticker, sell_timestamp, shares, sell_price, gain_loss_amount FROM trade_outcomes
            WHERE config_hash = :h AND sell_timestamp >= :since ORDER BY sell_timestamp
        """), {"h": config_hash, "since": since}).fetchall()
    filled_sells = [o for o in orders if o["action"] == "sell" and (o["status"] == "FILLED" or o["filled_qty"] > 0)]
    phantoms = []
    for r in outs:
        when = r.sell_timestamp.replace(tzinfo=timezone.utc)  # record_sell_outcome stores utcnow()
        ok = any(o["symbol"] == r.ticker and abs((o["entered"] - when).total_seconds()) <= 1800 for o in filled_sells)
        if not ok:
            phantoms.append(r)
    if phantoms:
        print(f"\n⚠️  {len(phantoms)} trade_outcomes row(s) have NO matching FILLED sell at Schwab (phantom sales — review, not deleted):")
        for r in phantoms:
            print(f"   id={r.id} {r.ticker} {r.sell_timestamp} {r.shares} sh @ {r.sell_price} gain {r.gain_loss_amount:+.2f}")
    else:
        print("\n✅ every trade_outcomes sell in the window has a matching FILLED order at Schwab")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--config-hash", default=os.getenv("CURRENT_CONFIG_HASH", "9ea09b9as"))
    ap.add_argument("--days", type=int, default=59, help="Schwab order history reaches back 60 days")
    a = ap.parse_args()
    reconcile(a.config_hash, a.days, a.apply)
