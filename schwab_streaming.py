"""
Schwab Streaming helpers for live intraday data flows.

This module wires the Schwab Trader API streaming client (schwab-py) into the
existing D-AI-Trader stack. It can:
  * Subscribe to Level One equity quotes for a configurable watchlist
  * Invoke user-provided callbacks on every quote
  * Listen for account activity events (order fills, cash moves) and trigger a
    holdings refresh so 'funds available' stays current intraday.

Usage example (see run_schwab_streaming.py):
    from schwab_streaming import run_streaming_forever
    run_streaming_forever(symbols=["SPY", "VTI"])

Environment variable DAI_STREAM_SYMBOLS (comma-separated) is honoured if the
symbols argument is omitted. When no list is supplied, the current Schwab
positions are loaded and streamed automatically.
"""

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

from schwab_client import (
    get_portfolio_snapshot,
    schwab_client,
)
from schwab_ledger import apply_account_activity as ledger_apply_account_activity

logger = logging.getLogger(__name__)

try:
    from schwab.streaming import StreamClient
except ImportError:  # pragma: no cover - handled in runtime messaging
    StreamClient = None  # type: ignore


QuoteHandler = Callable[[Dict[str, float]], None]
ActivityHandler = Callable[[Dict[str, Any]], None]


class SchwabStreamingService:
    """
    Lightweight wrapper around schwab-py's StreamClient.
    """

    def __init__(
        self,
        symbols: Optional[Sequence[str]] = None,
        on_quotes: Optional[QuoteHandler] = None,
        on_account_activity: Optional[ActivityHandler] = None,
    ):
        if not schwab_client.is_authenticated:
            schwab_client.authenticate()

        if not schwab_client.is_authenticated:
            raise RuntimeError("Unable to authenticate Schwab client for streaming/polling.")

        if not schwab_client.account_number:
            schwab_client._refresh_account_mapping()  # type: ignore[attr-defined]
        if not schwab_client.account_number:
            raise RuntimeError("Schwab account number unavailable; ensure account hash is configured.")

        self.symbols = self._resolve_symbols(symbols)
        self._quote_callback = on_quotes or (lambda _: None)
        self._activity_callback = on_account_activity or (lambda _: None)
        self._latest_quotes: Dict[str, float] = {}
        self._poll_interval = float(os.getenv("DAI_REST_POLL_SECS", "2"))

        self._stream_client = None
        self.mode = "poll"

        if StreamClient is not None:
            try:
                self._stream_client = StreamClient(schwab_client.client, account_id=int(schwab_client.account_number))
                self.mode = "stream"
            except Exception as exc:
                logger.warning("Falling back to REST polling (stream init failed): %s", exc)
                self._stream_client = None

    @staticmethod
    def _resolve_symbols(symbols: Optional[Sequence[str]]) -> List[str]:
        if symbols:
            return sorted({sym.upper() for sym in symbols})

        env_symbols = os.getenv("DAI_STREAM_SYMBOLS")
        if env_symbols:
            derived = {sym.strip().upper() for sym in env_symbols.split(",") if sym.strip()}
            if derived:
                return sorted(derived)

        snapshot = get_portfolio_snapshot()
        if not snapshot:
            return []
        holdings = snapshot.get("positions", [])
        derived = {position["symbol"].upper() for position in holdings if abs(position.get("shares", 0.0)) > 0}
        return sorted(derived)

    async def _handle_quotes(self, message: Dict[str, Any]) -> None:
        updates: Dict[str, float] = {}
        for row in message.get("content", []) or []:
            symbol = row.get("key")
            if not symbol:
                continue
            price = row.get(3) or row.get("3") or row.get("LAST_PRICE")
            if price is None:
                continue
            try:
                last = float(price)
            except (TypeError, ValueError):
                continue
            self._latest_quotes[symbol] = last
            updates[symbol] = last

        if updates:
            self._quote_callback(updates)

    async def _handle_account_activity(self, message: Dict[str, Any]) -> None:
        try:
            ledger_apply_account_activity(message)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to apply account activity to ledger: %s", exc)

        self._activity_callback(message)
        # Trigger holdings refresh so the dashboard displays updated funds/positions.
        try:
            from trading_interface import trading_interface  # local import to avoid circularity
            trading_interface.sync_schwab_positions()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to refresh holdings after account activity: %s", exc)

    async def run_forever(self) -> None:
        if self.mode == "stream" and self._stream_client is not None:
            if not self.symbols:
                logger.warning("No symbols resolved for Schwab streaming; nothing to subscribe to.")

            await self._stream_client.login()
            self._stream_client.add_level_one_equity_handler(lambda msg: asyncio.create_task(self._handle_quotes(msg)))
            if self.symbols:
                await self._stream_client.level_one_equity_subs(self.symbols)
                logger.info("Subscribed to Level One quotes for: %s", ", ".join(self.symbols))

            self._stream_client.add_account_activity_handler(
                lambda msg: asyncio.create_task(self._handle_account_activity(msg))
            )
            await self._stream_client.account_activity_sub()

            while True:
                await self._stream_client.handle_message()
        else:
            logger.info("Running Schwab ledger maintainer in REST polling mode (interval=%ss)", self._poll_interval)
            while True:
                try:
                    get_portfolio_snapshot()
                    from trading_interface import trading_interface  # local import to avoid circularity
                    trading_interface.sync_schwab_positions()
                except Exception as exc:
                    logger.warning("REST polling cycle failed: %s", exc)
                await asyncio.sleep(self._poll_interval)


def run_streaming_forever(
    symbols: Optional[Sequence[str]] = None,
    on_quotes: Optional[QuoteHandler] = None,
    on_account_activity: Optional[ActivityHandler] = None,
) -> None:
    """
    Convenience wrapper to run the streaming loop synchronously.
    """
    service = SchwabStreamingService(symbols=symbols, on_quotes=on_quotes, on_account_activity=on_account_activity)
    asyncio.run(service.run_forever())
