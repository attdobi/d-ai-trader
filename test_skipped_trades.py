#!/usr/bin/env python3
"""
Test script to verify that skipped trades are properly recorded
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import engine
from sqlalchemy import text
import json
from datetime import datetime

def test_skipped_trades():
    """Test that skipped trades are recorded with proper reasons"""
    
    print("=== Testing Skipped Trades Recording ===")
    
    # Check recent trade decisions
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT run_id, timestamp, data 
            FROM trade_decisions 
            ORDER BY timestamp DESC 
            LIMIT 5
        """))
        
        print("\nRecent trade decisions:")
        for row in result:
            print(f"\nRun ID: {row.run_id}")
            print(f"Timestamp: {row.timestamp}")
            
            try:
                data = json.loads(row.data) if isinstance(row.data, str) else row.data
                if isinstance(data, list):
                    for i, decision in enumerate(data):
                        print(f"  Decision {i+1}:")
                        print(f"    Action: {decision.get('action', 'N/A')}")
                        print(f"    Ticker: {decision.get('ticker', 'N/A')}")
                        print(f"    Amount: ${decision.get('amount_usd', 0):.2f}")
                        print(f"    Reason: {decision.get('reason', 'N/A')}")
                else:
                    print(f"  Data: {data}")
            except Exception as e:
                print(f"  Error parsing data: {e}")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_skipped_trades() 