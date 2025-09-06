#!/usr/bin/env python3
"""
Database Fix Script
This script fixes common database issues that can occur during development
"""

from config import engine
from sqlalchemy import text

def fix_database():
    """Fix common database issues"""

    print("🔧 Fixing database issues...")

    try:
        with engine.connect() as conn:
            # Reset any aborted transactions
            conn.execute(text('COMMIT'))

            # Test basic connectivity
            result = conn.execute(text('SELECT 1'))
            print("✅ Database connection working")

            # Check key tables
            tables_to_check = ['prompt_versions', 'holdings', 'summaries', 'trade_decisions']

            for table in tables_to_check:
                try:
                    result = conn.execute(text(f'SELECT COUNT(*) FROM {table}'))
                    count = result.fetchone()[0]
                    print(f"✅ {table}: {count} rows")
                except Exception as e:
                    print(f"⚠️  {table}: {e}")

        print("🎉 Database fix completed!")

    except Exception as e:
        print(f"❌ Database fix failed: {e}")

if __name__ == "__main__":
    fix_database()
