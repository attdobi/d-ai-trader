"""Whole-share order sizing for the cash account.

Schwab fills whole shares only. A ticket the Decider sizes below one share of the name
(DE 2026-09-17: $400 allocated at half size, $677.57 a share, $2,173 settled) used to
floor to zero shares and skip the buy with a message that read like a cash problem.
This module decides, in one place and without any config import, whether such a ticket
rounds up to exactly one share or is skipped, and why.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class WholeShareSizing:
    shares: int            # 0 = skip
    bound_by: str          # "model allocation" | "one-share minimum" | "max rail" | "settled funds"
    note: str              # one plain sentence for the log and the decision row


def whole_share_allocation(amount_usd: float, price: float, available_cash: float, *,
                           max_buy: float, min_buffer: float) -> WholeShareSizing:
    """Shares the allocation buys at `price`, rounding a sub-share ticket up to one share when
    that share fits inside the MAX rail and the settled funds behind the cash buffer."""
    if price <= 0:
        return WholeShareSizing(0, "settled funds", f"no usable price for a ${amount_usd:.2f} allocation")
    shares = floor(amount_usd / price)
    if shares >= 1:
        return WholeShareSizing(shares, "model allocation", f"{shares} share(s) at ${price:.2f} from a ${amount_usd:.2f} allocation")
    spendable = max(available_cash - min_buffer, 0.0)
    head = f"allocated ${amount_usd:.2f} buys no whole share at ${price:.2f}"
    if price > max_buy:
        return WholeShareSizing(0, "max rail", f"{head}; one share costs more than the ${max_buy:.0f} MAX rail")
    if price > spendable:
        return WholeShareSizing(0, "settled funds",
                                f"{head}; one share costs more than the ${spendable:.2f} of settled funds behind the ${min_buffer:.0f} buffer")
    return WholeShareSizing(1, "one-share minimum",
                            f"{head}; rounded up to 1 share (${price:.2f}) within the ${max_buy:.0f} MAX rail and ${available_cash:.2f} settled")


__all__ = ["WholeShareSizing", "whole_share_allocation"]
