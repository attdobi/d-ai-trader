#!/usr/bin/env python3
"""
Fix Default Config Hash Script
Cleans up existing 'default' config_hash records and ensures proper partitioning.
"""

from config import engine, set_gpt_model, set_prompt_version_mode, set_trading_mode, get_current_config_hash
from sqlalchemy import text
import sys

def fix_default_config_hash():
    """Fix the default config hash issue by moving data to proper config or cleaning up"""
    
    print("🔧 FIXING DEFAULT CONFIG HASH ISSUE")
    print("===================================")
    
    with engine.connect() as conn:
        # First, check how much data is in 'default'
        default_holdings = conn.execute(text("""
            SELECT COUNT(*) as count FROM holdings WHERE config_hash = 'default'
        """), {}).fetchone()
        
        default_summaries = conn.execute(text("""
            SELECT COUNT(*) as count FROM summaries WHERE config_hash = 'default'
        """), {}).fetchone()
        
        default_decisions = conn.execute(text("""
            SELECT COUNT(*) as count FROM trade_decisions WHERE config_hash = 'default'
        """), {}).fetchone()
        
        print(f"📊 Found in 'default' config:")
        print(f"   Holdings: {default_holdings.count}")
        print(f"   Summaries: {default_summaries.count}")
        print(f"   Trade Decisions: {default_decisions.count}")
        
        if default_holdings.count == 0 and default_summaries.count == 0 and default_decisions.count == 0:
            print("✅ No 'default' data found - nothing to fix!")
            return
        
        print("\n🧹 CLEANING UP 'default' CONFIG DATA")
        print("=====================================")
        
        # Option 1: Delete all 'default' data (safest for testing)
        response = input("\nDo you want to DELETE all 'default' config data? (y/N): ")
        
        if response.lower() == 'y':
            with engine.begin() as conn:
                # Delete default data
                result1 = conn.execute(text("DELETE FROM holdings WHERE config_hash = 'default'"), {})
                result2 = conn.execute(text("DELETE FROM summaries WHERE config_hash = 'default'"), {})
                result3 = conn.execute(text("DELETE FROM trade_decisions WHERE config_hash = 'default'"), {})
                result4 = conn.execute(text("DELETE FROM portfolio_history WHERE config_hash = 'default'"), {})
                result5 = conn.execute(text("DELETE FROM agent_feedback WHERE config_hash = 'default'"), {})
                result6 = conn.execute(text("DELETE FROM trade_outcomes WHERE config_hash = 'default'"), {})
                
                print(f"✅ Deleted {result1.rowcount} holdings")
                print(f"✅ Deleted {result2.rowcount} summaries") 
                print(f"✅ Deleted {result3.rowcount} trade decisions")
                print(f"✅ Deleted {result4.rowcount} portfolio history")
                print(f"✅ Deleted {result5.rowcount} agent feedback")
                print(f"✅ Deleted {result6.rowcount} trade outcomes")
                
                print("\n🎉 DEFAULT CONFIG DATA CLEANED UP!")
                print("All configurations should now be properly isolated.")
        else:
            print("❌ Cleanup cancelled - please manually review the 'default' data")
            return
        
        # Now remove the DEFAULT constraint from the schema
        print("\n🔧 REMOVING DEFAULT CONSTRAINTS FROM SCHEMA")
        print("============================================")
        
        try:
            with engine.begin() as conn:
                # Remove DEFAULT constraint from holdings table
                conn.execute(text("""
                    ALTER TABLE holdings 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from holdings.config_hash")
                
                # Remove DEFAULT constraint from summaries table  
                conn.execute(text("""
                    ALTER TABLE summaries 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from summaries.config_hash")
                
                # Check if trade_decisions has DEFAULT constraint and remove it
                conn.execute(text("""
                    ALTER TABLE trade_decisions 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from trade_decisions.config_hash")
                
        except Exception as e:
            print(f"⚠️  Note: {e}")
            print("This is expected if constraints were already removed.")
        
        print("\n✅ CONFIGURATION HASH SYSTEM FIXED!")
        print("All future operations will require explicit config_hash values.")
        print("Each parallel run will now be properly isolated.")

if __name__ == "__main__":
    fix_default_config_hash()
