"""Consolidated market-clock & timezone utilities for d-ai-trader."""

import os
import logging
import pytz
from datetime import datetime

logger = logging.getLogger(__name__)


def _load_local_timezone():
    """Load local timezone from env or system default."""
    tz_name = os.getenv("DAI_LOCAL_TIMEZONE") or os.getenv("TZ")
    if tz_name:
        try:
            return pytz.timezone(tz_name)
        except Exception as exc:
            logger.warning(
                f"Invalid timezone '{tz_name}' in env; falling back to system local. Error: {exc}"
            )
    try:
        return datetime.now().astimezone().tzinfo
    except Exception:
        return pytz.timezone("UTC")


class MarketClock:
    """Canonical source for timezone constants and market-hours checks."""

    LOCAL_TIMEZONE = _load_local_timezone()
    EASTERN_TIMEZONE = pytz.timezone("US/Eastern")
    MARKET_OPEN_TIME = "09:30"
    MARKET_CLOSE_TIME = "16:00"

    @classmethod
    def now_eastern(cls) -> datetime:
        """Current time in US/Eastern, timezone-aware."""
        return datetime.now(cls.EASTERN_TIMEZONE)

    @classmethod
    def now_local(cls) -> datetime:
        """Current time in local timezone, timezone-aware."""
        return datetime.now(cls.LOCAL_TIMEZONE)

    @classmethod
    def is_market_open(cls) -> bool:
        """Check if US stock market is open (M-F, 9:30-16:00 ET)."""
        now_et = cls.now_eastern()
        if now_et.weekday() >= 5:  # Saturday or Sunday
            return False
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et <= market_close

    @classmethod
    def is_market_hours(cls, start_hhmm: str, end_hhmm: str) -> bool:
        """Check if current ET time is between start_hhmm and end_hhmm (HH:MM)."""
        now_et = cls.now_eastern()
        sh, sm = map(int, start_hhmm.split(":"))
        eh, em = map(int, end_hhmm.split(":"))
        start = now_et.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now_et.replace(hour=eh, minute=em, second=0, microsecond=0)
        return start <= now_et <= end

    @classmethod
    def et_to_local(cls, hhmm: str) -> str:
        """Convert an ET HH:MM string to local-timezone HH:MM string."""
        try:
            hour, minute = map(int, hhmm.split(":"))
            now_et = datetime.now(cls.EASTERN_TIMEZONE)
            target_et = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
            target_local = target_et.astimezone(cls.LOCAL_TIMEZONE)
            return target_local.strftime("%H:%M")
        except Exception as exc:
            logger.warning(
                f"Failed to convert ET time '{hhmm}' to local; defaulting to same string. Error: {exc}"
            )
            return hhmm
