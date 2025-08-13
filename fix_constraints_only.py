#!/usr/bin/env python3
"""
Fix Database Constraints Only
Removes DEFAULT 'default' constraints without deleting any data.
"""

from config import engine
from sqlalchemy import text
import sys

def fix_constraints_only():
    """Remove DEFAULT 'default' constraints from config_hash columns"""
    
    print("🔧 REMOVING DEFAULT CONSTRAINTS ONLY")
    print("===================================")
    print("(No data will be deleted)")
    
    try:
        with engine.begin() as conn:
            # Remove DEFAULT constraint from holdings table
            try:
                conn.execute(text("""
                    ALTER TABLE holdings 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from holdings.config_hash")
            except Exception as e:
                print(f"ℹ️  holdings.config_hash: {e}")
            
            # Remove DEFAULT constraint from summaries table  
            try:
                conn.execute(text("""
                    ALTER TABLE summaries 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from summaries.config_hash")
            except Exception as e:
                print(f"ℹ️  summaries.config_hash: {e}")
            
            # Remove DEFAULT constraint from trade_decisions if it has one
            try:
                conn.execute(text("""
                    ALTER TABLE trade_decisions 
                    ALTER COLUMN config_hash DROP DEFAULT
                """))
                print("✅ Removed DEFAULT constraint from trade_decisions.config_hash")
            except Exception as e:
                print(f"ℹ️  trade_decisions.config_hash: {e}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    
    print("\n✅ CONSTRAINT FIXES COMPLETE!")
    print("Future operations will require explicit config_hash values.")
    print("Existing 'default' data is preserved and won't interfere with new configs.")

if __name__ == "__main__":
    fix_constraints_only()
