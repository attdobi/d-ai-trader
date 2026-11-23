"""Read Schwab share fills and their net cash movements without using position cost basis."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Missing or invalid trade amount") from None
    if not number.is_finite():
        raise ValueError("Non-finite trade amount")
    return number


def transaction_fills(transactions, ticker):
    """Return signed fills in time order. An ambiguous transaction leaves the campaign unscored.

    netAmount belongs to the whole activity, including its fees. It can fund a single
    security with multiple same-side fills, but cannot be allocated across securities.
    A blank order ID identifies a fill with no proven strategy ownership.
    """
    if not isinstance(transactions, list):
        raise ValueError("Missing transaction list")
    symbol = ticker.strip().upper()
    fills = {}
    for row in transactions:
        if not isinstance(row, dict):
            raise ValueError("Invalid activity")
        items = row.get("transferItems") or []
        if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
            raise ValueError("Invalid activity legs")
        if any(i.get("instrument") is not None and not isinstance(i["instrument"], dict) for i in items):
            raise ValueError("Invalid activity instrument")
        securities = [i for i in items if (i.get("instrument") or {}).get("assetType") != "CURRENCY"]
        relevant = [i for i in securities if str((i.get("instrument") or {}).get("symbol") or "").upper() == symbol]
        if not relevant:
            continue
        if row.get("type") != "TRADE":
            if row.get("type") == "DIVIDEND_OR_INTEREST" and all(_number(i.get("amount", 0)) == 0 for i in relevant):
                continue
            raise ValueError("Non-trade security movement requires reconciliation")
        if row.get("status") != "VALID" or len(securities) != len(relevant):
            raise ValueError("Unsettled or multi-security activity")
        if any(i["instrument"].get("assetType") not in {"EQUITY", "COLLECTIVE_INVESTMENT"} for i in relevant):
            raise ValueError("Unsupported security type")
        quantities = [_number(i.get("amount")) for i in relevant]
        prices = [_number(i.get("price")) for i in relevant]
        if any(q == 0 or (q > 0) != (quantities[0] > 0) for q in quantities) or min(prices) <= 0:
            raise ValueError("Invalid or mixed-side equity fills")
        quantity = sum(quantities)
        gross = sum(q * p for q, p in zip(quantities, prices))
        net = _number(row.get("netAmount"))
        if net * quantity >= 0:
            raise ValueError("Inconsistent signed net cash")
        activity_id = str(row.get("activityId") or "").strip()
        if not activity_id:
            raise ValueError("Missing activity identifier")
        at = datetime.fromisoformat(str(row.get("time")).replace("Z", "+00:00").replace("+0000", "+00:00"))
        if at.utcoffset() is None:
            raise ValueError("Activity time has no offset")
        fill = {"order_id": str(row.get("orderId") or "").strip(), "activity_id": activity_id,
                "quantity": float(quantity), "price": float(gross / quantity),
                "net_amount": float(net), "at": at.astimezone(timezone.utc)}
        if activity_id in fills and fills[activity_id] != fill:
            raise ValueError("Conflicting copies of a broker activity")
        fills[activity_id] = fill
    return sorted(fills.values(), key=lambda f: (f["at"], f["activity_id"]))
