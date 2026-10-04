"""Whole-share order sizing, position caps and the per-cycle ticket split for the cash account.

Schwab fills whole shares only. A ticket the Decider sizes below one share of the name
(DE 2026-09-17: $400 allocated at half size, $677.57 a share, $2,173 settled) used to
floor to zero shares and skip the buy with a message that read like a cash problem.
This module decides, in one place and without any config import, whether such a ticket
rounds up to exactly one share or is skipped, and why.

It also holds the MAX_POSITION_* / MAX_TOTAL_INVESTMENT* caps (`resolve_cap` is the max-of
rule TradingSafetyManager uses; `CapBook` applies it on the scheduled path) and the split
of a cycle's sells and buys under DAILY_TICKET_CAP / DAILY_BUY_CAP / one-trade pilot mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, isfinite
from typing import Dict, List, Optional, Tuple

INF = float("inf")
_EPS = 1e-9          # a room of exactly n × price still fits n shares despite float noise

POSITION_CAP = "position cap"
TOTAL_CAP = "total investment cap"


@dataclass(frozen=True)
class WholeShareSizing:
    shares: int            # 0 = skip
    bound_by: str          # "model allocation" | "one-share minimum" | "max rail" | "settled funds"
                           # | "position cap" | "total investment cap"
    note: str              # one plain sentence for the log and the decision row
    cap_usd: Optional[float] = None   # the binding cap's dollar value when bound_by names a cap


def resolve_cap(floor_usd: float, fraction: float, account_value: float) -> float:
    """The active cap: the larger of an absolute floor and a fraction of account value.

    A non-positive floor or fraction is unset; with neither set there is no cap (inf).
    This is the max-of rule for MAX_POSITION_VALUE / MAX_POSITION_FRACTION and
    MAX_TOTAL_INVESTMENT / MAX_TOTAL_INVESTMENT_FRACTION, shared with TradingSafetyManager.
    """
    limits = []
    if floor_usd and floor_usd > 0:
        limits.append(float(floor_usd))
    if fraction and fraction > 0 and account_value and account_value > 0:
        limits.append(float(account_value) * float(fraction))
    return max(limits) if limits else INF


@dataclass(frozen=True)
class PositionCaps:
    """The caps one buy must fit under, in dollars of market value after the buy."""
    position_limit: float = INF      # resolved MAX_POSITION_* cap
    total_limit: float = INF         # resolved MAX_TOTAL_INVESTMENT* cap
    existing_position: float = 0.0   # market value already held in this ticker
    invested: float = 0.0            # market value of all positions

    def _fit(self, limit: float, used: float, price: float) -> float:
        if not isfinite(limit):
            return INF
        return floor(max(limit - used, 0.0) / price + _EPS)

    def binding(self, price: float) -> Tuple[float, Optional[str], str, Optional[float]]:
        """(shares that fit, binding cap name, plain phrase naming it, cap dollars) at `price`.
        The tighter cap binds; on a tie the position cap is named. No finite cap → (inf, None, "", None)."""
        pos_fit = self._fit(self.position_limit, self.existing_position, price)
        tot_fit = self._fit(self.total_limit, self.invested, price)
        if not isfinite(pos_fit) and not isfinite(tot_fit):
            return INF, None, "", None
        if pos_fit <= tot_fit:
            room = max(self.position_limit - self.existing_position, 0.0)
            return pos_fit, POSITION_CAP, (
                f"${room:,.2f} left under the ${self.position_limit:,.2f} position cap "
                f"(${self.existing_position:,.2f} already held)"), self.position_limit
        room = max(self.total_limit - self.invested, 0.0)
        return tot_fit, TOTAL_CAP, (
            f"${room:,.2f} left under the ${self.total_limit:,.2f} total investment cap "
            f"(${self.invested:,.2f} already invested)"), self.total_limit


NO_CAPS = PositionCaps()


def whole_share_allocation(amount_usd: float, price: float, available_cash: float, *,
                           max_buy: float, min_buffer: float,
                           caps: Optional[PositionCaps] = None) -> WholeShareSizing:
    """Shares the allocation buys at `price`, rounding a sub-share ticket up to one share when
    that share fits inside the MAX rail, the settled funds behind the cash buffer and the
    position / total-investment caps. A full-share ticket is cut to what the caps leave room for."""
    caps = caps or NO_CAPS
    if price <= 0:
        return WholeShareSizing(0, "settled funds", f"no usable price for a ${amount_usd:.2f} allocation")
    shares = floor(amount_usd / price)
    if shares >= 1:
        fit, cap_name, cap_phrase, cap_usd = caps.binding(price)
        if fit >= shares:
            return WholeShareSizing(shares, "model allocation", f"{shares} share(s) at ${price:.2f} from a ${amount_usd:.2f} allocation")
        if fit <= 0:
            return WholeShareSizing(0, cap_name,
                                    f"allocated ${amount_usd:.2f} at ${price:.2f} buys nothing; one share costs more than the {cap_phrase}",
                                    cap_usd)
        fit = int(fit)
        return WholeShareSizing(fit, cap_name,
                                f"{fit} share(s) at ${price:.2f}, cut from {shares} to fit the {cap_phrase}", cap_usd)
    spendable = max(available_cash - min_buffer, 0.0)
    head = f"allocated ${amount_usd:.2f} buys no whole share at ${price:.2f}"
    if price > max_buy:
        return WholeShareSizing(0, "max rail", f"{head}; one share costs more than the ${max_buy:.0f} MAX rail")
    if price > spendable:
        return WholeShareSizing(0, "settled funds",
                                f"{head}; one share costs more than the ${spendable:.2f} of settled funds behind the ${min_buffer:.0f} buffer")
    fit, cap_name, cap_phrase, cap_usd = caps.binding(price)
    if fit < 1:
        return WholeShareSizing(0, cap_name, f"{head}; one share costs more than the {cap_phrase}", cap_usd)
    return WholeShareSizing(1, "one-share minimum",
                            f"{head}; rounded up to 1 share (${price:.2f}) within the ${max_buy:.0f} MAX rail and ${available_cash:.2f} settled")


@dataclass
class CapBook:
    """One cycle's position book for the caps: market value per ticker and the account value
    the fractional caps resolve against. `record_buy` keeps it current between buys so a
    second buy in the same cycle sees the first."""
    position_limit: float
    total_limit: float
    account_value: float
    positions: Dict[str, float] = field(default_factory=dict)
    source: str = "holdings"

    @classmethod
    def build(cls, positions: Dict[str, float], cash: float, *, account_value: Optional[float] = None,
              max_position_value: float, max_position_fraction: float,
              max_total_investment: float, max_total_investment_fraction: float,
              source: str = "holdings") -> "CapBook":
        book = {str(t).upper(): float(v or 0.0) for t, v in (positions or {}).items() if t}
        invested = sum(book.values())
        acct = float(account_value) if account_value and account_value > 0 else invested + max(float(cash or 0.0), 0.0)
        return cls(
            position_limit=resolve_cap(max_position_value, max_position_fraction, acct),
            total_limit=resolve_cap(max_total_investment, max_total_investment_fraction, acct),
            account_value=acct,
            positions=book,
            source=source,
        )

    @property
    def invested(self) -> float:
        return sum(self.positions.values())

    def caps_for(self, ticker: str) -> PositionCaps:
        return PositionCaps(self.position_limit, self.total_limit,
                            self.positions.get(str(ticker).upper(), 0.0), self.invested)

    def record_buy(self, ticker: str, usd: float) -> None:
        key = str(ticker).upper()
        self.positions[key] = self.positions.get(key, 0.0) + float(usd or 0.0)

    def describe(self) -> str:
        def _usd(v):
            return f"${v:,.2f}" if isfinite(v) else "none"
        return (f"position cap {_usd(self.position_limit)}, total investment cap {_usd(self.total_limit)} "
                f"(account ${self.account_value:,.2f}, invested ${self.invested:,.2f}, from {self.source})")


@dataclass(frozen=True)
class CycleSplit:
    sells: List[dict]
    buys: List[dict]
    dropped: List[Tuple[dict, str, str]]   # (decision, execution_error, skip reason)
    sell_limit: Optional[int] = None       # None = no per-cycle sell cap (simulation)
    buy_limit: Optional[int] = None        # None = no per-cycle buy cap (simulation, pilot off)
    pilot_binds: bool = False              # the buy limit is one-trade pilot mode's single buy


def split_cycle_tickets(sells: List[dict], buys: List[dict], *, sell_cap: int, buy_cap: int,
                        one_trade_mode: bool, live: bool) -> CycleSplit:
    """Which sells and buys execute this cycle, in decision order.

    Live mode bounds a cycle at `sell_cap` sells (DAILY_TICKET_CAP) and `buy_cap` buys
    (DAILY_BUY_CAP). One-trade pilot mode limits BUYS to one per cycle (the min with the buy
    cap); it never holds back a sell, so profit-taking and kill-breach exits still execute.
    """
    sell_limit = max(int(sell_cap), 0) if live else None
    buy_limit = max(int(buy_cap), 0) if live else None
    if one_trade_mode:
        buy_limit = 1 if buy_limit is None else min(buy_limit, 1)
    pilot_binds = bool(one_trade_mode) and buy_limit == 1

    dropped: List[Tuple[dict, str, str]] = []
    kept_sells = list(sells)
    if sell_limit is not None and len(kept_sells) > sell_limit:
        for d in kept_sells[sell_limit:]:
            dropped.append((d, f"Not executed — exceeded the {sell_limit}-sell cap for this cycle",
                            f"Live mode limit reached - max {sell_limit} sells executed"))
        kept_sells = kept_sells[:sell_limit]
    kept_buys = list(buys)
    if buy_limit is not None and len(kept_buys) > buy_limit:
        for d in kept_buys[buy_limit:]:
            if pilot_binds:
                dropped.append((d, "Not executed — one-trade pilot mode allows 1 buy per cycle",
                                "One-trade pilot mode - max 1 buy per cycle; additional buy skipped"))
            else:
                dropped.append((d, f"Not executed — exceeded the {buy_limit}-buy cap for this cycle",
                                f"Live mode limit reached - max {buy_limit} buys executed"))
        kept_buys = kept_buys[:buy_limit]
    return CycleSplit(kept_sells, kept_buys, dropped, sell_limit, buy_limit, pilot_binds)


__all__ = [
    "WholeShareSizing", "whole_share_allocation",
    "resolve_cap", "PositionCaps", "NO_CAPS", "CapBook", "POSITION_CAP", "TOTAL_CAP",
    "CycleSplit", "split_cycle_tickets",
]
