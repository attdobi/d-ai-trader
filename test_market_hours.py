#!/usr/bin/env python3
"""
Test market hours detection
"""
import os
import sys
from datetime import datetime
import pytz

# Setup
os.environ.setdefault("DAI_TRADER_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decider_agent import is_market_open

PACIFIC_TZ = pytz.timezone('US/Pacific')
EASTERN_TZ = pytz.timezone('US/Eastern')

# Get current times
now_pacific = datetime.now(PACIFIC_TZ)
now_eastern = now_pacific.astimezone(EASTERN_TZ)
now_utc = now_pacific.astimezone(pytz.UTC)

print("="*60)
print("Market Hours Test")
print("="*60)
print(f"\nCurrent Times:")
print(f"  Pacific: {now_pacific.strftime('%I:%M:%S %p %Z')} ({now_pacific.strftime('%A')})")
print(f"  Eastern: {now_eastern.strftime('%I:%M:%S %p %Z')} ({now_eastern.strftime('%A')})")
print(f"  UTC:     {now_utc.strftime('%I:%M:%S %p %Z')}")

print(f"\nMarket Hours (Eastern Time):")
print(f"  Open:  9:30 AM ET")
print(f"  Close: 4:00 PM ET")
print(f"  Days:  Monday-Friday")

market_open = is_market_open()
print(f"\n{'✅ MARKET IS OPEN' if market_open else '⛔ MARKET IS CLOSED'}")

if not market_open:
    # Show when market opens next
    if now_eastern.weekday() >= 5:  # Weekend
        print(f"\n  Market opens Monday at 9:30 AM ET")
    elif now_eastern.hour < 9 or (now_eastern.hour == 9 and now_eastern.minute < 30):
        print(f"\n  Market opens today at 9:30 AM ET")
    else:
        print(f"\n  Market opens tomorrow at 9:30 AM ET")

print("="*60)

