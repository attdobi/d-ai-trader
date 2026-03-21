"""Tests for shared.market_clock.MarketClock"""
import pytest
import pytz
from datetime import datetime
from unittest.mock import patch

ET = pytz.timezone("US/Eastern")


def _make_et_datetime(year, month, day, hour, minute, second=0):
    """Helper: create a timezone-aware datetime in US/Eastern."""
    return ET.localize(datetime(year, month, day, hour, minute, second))


def _mock_now(fixed_dt):
    """Create a side_effect for datetime.now that returns fixed_dt when tz is given."""
    def _now(tz=None):
        if tz is not None:
            return fixed_dt.astimezone(tz)
        return fixed_dt.replace(tzinfo=None)
    return _now


# --- is_market_open tests ---

@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_open_weekday_during_hours(mock_dt):
    """Wednesday 10:00 ET => market open"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 10, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is True


@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_closed_weekend_saturday(mock_dt):
    """Saturday => market closed"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 21, 12, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is False


@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_closed_weekend_sunday(mock_dt):
    """Sunday => market closed"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 22, 12, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is False


# --- Boundary tests ---

@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_closed_before_open(mock_dt):
    """9:29 AM ET => closed"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 9, 29))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is False


@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_open_at_930(mock_dt):
    """9:30 AM ET => open"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 9, 30))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is True


@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_open_at_1600(mock_dt):
    """4:00 PM ET => still open (<=)"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 16, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is True


@patch("shared.market_clock.datetime", wraps=datetime)
def test_market_closed_after_1600(mock_dt):
    """4:01 PM ET => closed"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 16, 1))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_open() is False


# --- is_market_hours tests ---

@patch("shared.market_clock.datetime", wraps=datetime)
def test_is_market_hours_in_range(mock_dt):
    """10:00 ET is within 09:00-11:00"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 10, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_hours("09:00", "11:00") is True


@patch("shared.market_clock.datetime", wraps=datetime)
def test_is_market_hours_out_of_range(mock_dt):
    """8:00 ET is outside 09:00-11:00"""
    mock_dt.now.side_effect = _mock_now(_make_et_datetime(2026, 3, 18, 8, 0))
    from shared.market_clock import MarketClock
    assert MarketClock.is_market_hours("09:00", "11:00") is False


# --- et_to_local tests ---

def test_et_to_local_returns_valid_hhmm():
    """et_to_local should return a valid HH:MM string"""
    from shared.market_clock import MarketClock
    result = MarketClock.et_to_local("09:30")
    assert len(result) == 5
    assert result[2] == ":"
    h, m = map(int, result.split(":"))
    assert 0 <= h <= 23
    assert 0 <= m <= 59


# --- now_eastern tests ---

def test_now_eastern_is_aware():
    """now_eastern() should return timezone-aware datetime in US/Eastern"""
    from shared.market_clock import MarketClock
    dt = MarketClock.now_eastern()
    assert dt.tzinfo is not None
    tz_str = str(dt.tzinfo)
    assert any(x in tz_str for x in ("Eastern", "EDT", "EST", "US/Eastern"))


# --- now_local tests ---

def test_now_local_is_aware():
    """now_local() should return timezone-aware datetime"""
    from shared.market_clock import MarketClock
    dt = MarketClock.now_local()
    assert dt.tzinfo is not None
