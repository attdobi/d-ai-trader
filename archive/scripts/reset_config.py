#!/usr/bin/env python3
"""
Reset Configuration Script
Resets the current configuration to a fresh $10,000 state by clearing all data.
"""

from config import engine, get_current_config_hash
from sqlalchemy import text
import sys

def reset_current_config():
    """Reset the current configuration to fresh $10,000 state"""
    config_hash = get_current_config_hash()
    print(f"🔄 Resetting configuration {config_hash} to fresh $10,000 state...")
    
    try:
        with engine.begin() as conn:
            # Delete existing data for this config
            result1 = conn.execute(text("DELETE FROM holdings WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result2 = conn.execute(text("DELETE FROM portfolio_history WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result3 = conn.execute(text("DELETE FROM trade_decisions WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result4 = conn.execute(text("DELETE FROM trade_outcomes WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result5 = conn.execute(text("DELETE FROM summaries WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result6 = conn.execute(text("DELETE FROM agent_feedback WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            
            print(f"📊 Cleared data:")
            print(f"   - {result1.rowcount} holdings")
            print(f"   - {result2.rowcount} portfolio history entries")
            print(f"   - {result3.rowcount} trade decisions")
            print(f"   - {result4.rowcount} trade outcomes")
            print(f"   - {result5.rowcount} summaries")
            print(f"   - {result6.rowcount} feedback entries")
            
            # Insert fresh cash holding
            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, 
                                    purchase_timestamp, current_price_timestamp, total_value, 
                                    current_value, gain_loss, reason, is_active)
                VALUES (:config_hash, 'CASH', 1, 10000, 10000, now(), now(), 
                        10000, 10000, 0, 'Initial cash - reset', TRUE)
            """), {"config_hash": config_hash})
            
            # Insert fresh portfolio snapshot
            conn.execute(text("""
                INSERT INTO portfolio_history (total_portfolio_value, cash_balance, total_invested, 
                                             total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
                VALUES (10000, 10000, 0, 0, 0, '[{"ticker": "CASH", "current_value": 10000}]', :config_hash)
            """), {"config_hash": config_hash})
            
        print(f"✅ Configuration {config_hash} reset complete!")
        print(f"💰 Portfolio now starts at $10,000 with $0 Net Gain/Loss")
        return True
        
    except Exception as e:
        print(f"❌ Error resetting configuration: {e}")
        return False

def reset_specific_config(config_hash):
    """Reset a specific configuration to fresh $10,000 state"""
    print(f"🔄 Resetting specific configuration {config_hash} to fresh $10,000 state...")
    
    try:
        with engine.begin() as conn:
            # Check if config exists
            result = conn.execute(text("SELECT COUNT(*) as count FROM holdings WHERE config_hash = :config_hash"), {"config_hash": config_hash}).fetchone()
            if result.count == 0:
                print(f"⚠️  Configuration {config_hash} not found")
                return False
            
            # Delete existing data for this config
            result1 = conn.execute(text("DELETE FROM holdings WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result2 = conn.execute(text("DELETE FROM portfolio_history WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result3 = conn.execute(text("DELETE FROM trade_decisions WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result4 = conn.execute(text("DELETE FROM trade_outcomes WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result5 = conn.execute(text("DELETE FROM summaries WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            result6 = conn.execute(text("DELETE FROM agent_feedback WHERE config_hash = :config_hash"), {"config_hash": config_hash})
            
            print(f"📊 Cleared data for {config_hash}:")
            print(f"   - {result1.rowcount} holdings")
            print(f"   - {result2.rowcount} portfolio history entries")
            print(f"   - {result3.rowcount} trade decisions")
            print(f"   - {result4.rowcount} trade outcomes")
            print(f"   - {result5.rowcount} summaries")
            print(f"   - {result6.rowcount} feedback entries")
            
            # Insert fresh cash holding
            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, 
                                    purchase_timestamp, current_price_timestamp, total_value, 
                                    current_value, gain_loss, reason, is_active)
                VALUES (:config_hash, 'CASH', 1, 10000, 10000, now(), now(), 
                        10000, 10000, 0, 'Initial cash - reset', TRUE)
            """), {"config_hash": config_hash})
            
            # Insert fresh portfolio snapshot
            conn.execute(text("""
                INSERT INTO portfolio_history (total_portfolio_value, cash_balance, total_invested, 
                                             total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
                VALUES (10000, 10000, 0, 0, 0, '[{"ticker": "CASH", "current_value": 10000}]', :config_hash)
            """), {"config_hash": config_hash})
            
        print(f"✅ Configuration {config_hash} reset complete!")
        print(f"💰 Portfolio now starts at $10,000 with $0 Net Gain/Loss")
        return True
        
    except Exception as e:
        print(f"❌ Error resetting configuration: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Reset specific config hash
        target_hash = sys.argv[1]
        reset_specific_config(target_hash)
    else:
        # Reset current config
        reset_current_config()
