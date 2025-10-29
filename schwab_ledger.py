"""
Shadow ledger to keep Schwab "funds available" realistic between REST snapshots.

The Schwab Trader API returns account balances on demand, but CASH accounts can
trade with same-day proceeds even when `cashAvailableForTrading` remains zero
until settlement. This module tracks intraday fills and open orders so the UI
can present an "effective" buying power figure in real time.

The ledger is intentionally lightweight and process-local. It is updated via:
  * Portfolio snapshots (to seed settled cash / totals)
  * Streaming account-activity events (fills, order status changes)
  * REST transactions fetched for reconciliation
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ShadowLedger:
    cash_settled: float = 0.0
    unsettled_sells: float = 0.0
    unsettled_buys: float = 0.0
    open_order_reserve: float = 0.0
    fees_reserve: float = 0.0
    last_refresh: Optional[datetime] = None

    def effective_funds(self, baseline: float, allow_unsettled: bool) -> float:
        baseline = float(baseline)
        patched = baseline - self.open_order_reserve - self.fees_reserve
        if allow_unsettled:
            patched += max(0.0, self.unsettled_sells - self.unsettled_buys)
        else:
            patched -= max(0.0, self.unsettled_buys)
        return max(0.0, round(patched, 2))

    def reset(self) -> None:
        self.cash_settled = 0.0
        self.unsettled_sells = 0.0
        self.unsettled_buys = 0.0
        self.open_order_reserve = 0.0
        self.fees_reserve = 0.0
        self.last_refresh = None

    def clear_intraday(self) -> None:
        self.unsettled_sells = 0.0
        self.unsettled_buys = 0.0
        self.open_order_reserve = 0.0
        self.fees_reserve = 0.0

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.last_refresh:
            payload["last_refresh"] = self.last_refresh.isoformat()
        return payload


_ledger = ShadowLedger()
ALLOW_UNSETTLED_DEFAULT = os.getenv("DAI_ALLOW_UNSETTLED_FOR_TRADE", "1").lower() in {"1", "true", "yes"}


def get_ledger_state() -> Dict[str, Any]:
    """Return the current shadow ledger as a dict (for diagnostics)."""
    return _ledger.to_dict()


def reset() -> None:
    """Full reset of the ledger (including settled cash)."""
    _ledger.reset()


def components() -> Dict[str, float]:
    """Return human-friendly components for UI display."""
    same_day_net = _ledger.unsettled_sells - _ledger.unsettled_buys
    return {
        "cash_settled": round(_ledger.cash_settled, 2),
        "open_buy_reserve": round(_ledger.open_order_reserve, 2),
        "unsettled_proceeds": round(_ledger.unsettled_sells, 2),
        "unsettled_buys": round(_ledger.unsettled_buys, 2),
        "fees_reserve": round(_ledger.fees_reserve, 2),
        "same_day_net": round(same_day_net, 2),
    }


def seed_from_balances(balances: Dict[str, Any]) -> None:
    """
    Initialize ledger using the latest Schwab snapshot.

    Should be called whenever `currentBalances` are refreshed.
    """
    try:
        total_cash = float(balances.get("totalCash") or 0.0)
        _ledger.cash_settled = max(0.0, total_cash)
        _ledger.last_refresh = datetime.utcnow()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Unable to seed ledger from balances: %s", exc)


def reset_intraday_adjustments() -> None:
    """Clear intraday adjustments before recomputing them from transactions."""
    _ledger.clear_intraday()


def set_order_reserve(value: float) -> None:
    """Record the estimated reserve for open orders."""
    try:
        _ledger.open_order_reserve = max(0.0, float(value or 0.0))
    except Exception:  # pragma: no cover
        _ledger.open_order_reserve = 0.0


def apply_fill(side: str, amount: float, fees: float = 0.0) -> None:
    """
    Register a filled order to update unsettled cash.

    Args:
        side: Buy/Sell direction (any string beginning with BUY/SELL).
        amount: Gross fill amount (price * quantity).
        fees: Commission/fees to subtract from proceeds or add to debits.
    """
    s_upper = side.upper()
    net_amount = max(0.0, float(amount or 0.0))
    fee_amount = max(0.0, float(fees or 0.0))

    if s_upper.startswith("SELL"):
        _ledger.unsettled_sells += max(0.0, net_amount - fee_amount)
    elif s_upper.startswith("BUY"):
        _ledger.unsettled_buys += max(0.0, net_amount + fee_amount)

    _ledger.fees_reserve += fee_amount


def apply_transaction_record(tx: Dict[str, Any]) -> None:
    """
    Ingest a transaction payload (from /transactions) and update the ledger.
    """
    try:
        t_type = (tx.get("type") or "").upper()
        if t_type != "TRADE":
            return

        instruction = (
            tx.get("transactionItem", {}).get("instruction")
            or tx.get("instruction")
            or ""
        ).upper()
        amount = float(tx.get("amount") or tx.get("netAmount") or tx.get("price") or 0.0)
        fees = float(tx.get("fees") or 0.0)
        apply_fill(instruction, abs(amount), fees=fees)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Unable to apply transaction record to ledger: %s", exc)


def apply_account_activity(message: Dict[str, Any]) -> None:
    """
    Parse Schwab account-activity stream message.
    """
    try:
        data = message.get("content") or message.get("data") or []
        if isinstance(data, dict):
            data = data.get("content") or []

        for entry in data:
            activity = entry.get("activity") or entry
            if not isinstance(activity, dict):
                continue

            activity_type = (activity.get("activityType") or activity.get("type") or "").upper()
            if activity_type not in {"EXECUTION", "TRADE"}:
                continue

            instruction = (
                activity.get("orderAction")
                or activity.get("instruction")
                or activity.get("side")
                or ""
            ).upper()
            quantity = float(activity.get("quantity") or 0.0)
            price = float(activity.get("price") or activity.get("fillPrice") or 0.0)
            fees = float(activity.get("fees") or 0.0)
            amount = abs(quantity * price)
            apply_fill(instruction, amount, fees=fees)
    except Exception as exc:  # pragma: no cover
        logger.debug("Unable to apply account activity to ledger: %s", exc)


OPEN_ORDER_STATUSES = {
    "WORKING",
    "QUEUED",
    "PENDING_ACTIVATION",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "ACCEPTED",
    "AWAITING_PARENT_ORDER",
}


def _estimate_order_reserve(order: Dict[str, Any]) -> float:
    try:
        status = (order.get("status") or "").upper()
        if status not in OPEN_ORDER_STATUSES:
            return 0.0

        order_type = (order.get("orderType") or "").upper()
        price_hint = float(order.get("price") or order.get("enteredPrice") or 0.0)
        reserve = 0.0
        for leg in order.get("orderLegCollection") or []:
            instruction = (leg.get("instruction") or "").upper()
            qty = float(leg.get("quantity") or leg.get("orderedQuantity") or 0.0)
            if qty <= 0 or not instruction.startswith("BUY"):
                continue
            leg_price = float(leg.get("price") or price_hint or 0.0)
            if leg_price <= 0 and order_type == "MARKET":
                leg_price = float(leg.get("estimatedPrice") or 0.0)
            if leg_price <= 0:
                continue
            reserve += leg_price * qty
        return reserve
    except Exception:
        return 0.0


def reconcile_from_rest(open_orders: Iterable[Dict[str, Any]], transactions_today: Optional[Iterable[Dict[str, Any]]] = None) -> None:
    """Rebuild ledger values from REST snapshots."""
    reset_intraday_adjustments()
    total_reserve = 0.0
    for order in open_orders or []:
        total_reserve += max(0.0, _estimate_order_reserve(order))
    set_order_reserve(total_reserve)

    if transactions_today:
        for tx in transactions_today:
            apply_transaction_record(tx)


def compute_effective_funds(baseline: float, allow_unsettled: Optional[bool] = None) -> float:
    """
    Combine the baseline figure from Schwab with ledger adjustments.
    """
    if allow_unsettled is None:
        allow_unsettled = ALLOW_UNSETTLED_DEFAULT
    return _ledger.effective_funds(float(baseline), allow_unsettled)
