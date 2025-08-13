#!/usr/bin/env python3
"""
Database Migration Script for Parallel Run Support
This script updates the database schema to support multiple parallel configurations
"""
import sys
from sqlalchemy import text
from config import engine

def migrate_database():
    """Migrate database schema for parallel run support"""
    print("🔄 Starting database migration for parallel run support...")
    
    try:
        with engine.begin() as conn:
            
            # 1. Create run_configurations table
            print("📋 Creating run_configurations table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS run_configurations (
                    config_hash TEXT PRIMARY KEY,
                    gpt_model TEXT NOT NULL,
                    prompt_mode TEXT NOT NULL,
                    forced_prompt_version INTEGER,
                    trading_mode TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # 2. Add config_hash to existing tables (if column doesn't exist)
            tables_to_update = [
                "summaries",
                "trade_decisions", 
                "holdings",
                "portfolio_history",
                "trade_outcomes",
                "agent_feedback",
                "agent_instruction_updates",
                "ai_agent_feedback_responses",
                "system_runs",
                "processed_summaries"
            ]
            
            for table in tables_to_update:
                print(f"🔧 Updating table: {table}")
                
                # Check if table exists
                table_exists = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = :table_name
                    )
                """), {"table_name": table}).fetchone()[0]
                
                if table_exists:
                    # Check if config_hash column exists
                    column_exists = conn.execute(text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = :table_name AND column_name = 'config_hash'
                        )
                    """), {"table_name": table}).fetchone()[0]
                    
                    if not column_exists:
                        # Add config_hash column
                        conn.execute(text(f"""
                            ALTER TABLE {table} 
                            ADD COLUMN config_hash TEXT NOT NULL DEFAULT 'default'
                        """))
                        print(f"  ✅ Added config_hash column to {table}")
                        
                        # For holdings table, also need to handle unique constraint
                        if table == "holdings":
                            # Drop old primary key if it exists on ticker
                            try:
                                conn.execute(text("""
                                    ALTER TABLE holdings DROP CONSTRAINT IF EXISTS holdings_pkey
                                """))
                                conn.execute(text("""
                                    ALTER TABLE holdings ADD COLUMN id SERIAL PRIMARY KEY
                                """))
                                conn.execute(text("""
                                    ALTER TABLE holdings ADD CONSTRAINT holdings_config_ticker_unique 
                                    UNIQUE(config_hash, ticker)
                                """))
                                print(f"  ✅ Updated holdings table structure")
                            except Exception as e:
                                print(f"  ⚠️  Holdings table structure update: {e}")
                    else:
                        print(f"  ✅ {table} already has config_hash column")
                else:
                    print(f"  ⚠️  Table {table} does not exist, will be created by application")
            
            # 3. Create performance comparison views
            print("📊 Creating performance comparison views...")
            
            # Configuration performance summary view
            conn.execute(text("""
                CREATE OR REPLACE VIEW configuration_performance AS
                SELECT 
                    rc.config_hash,
                    rc.description,
                    rc.gpt_model,
                    rc.prompt_mode,
                    rc.trading_mode,
                    rc.created_at,
                    rc.last_used,
                    COALESCE(ph.latest_portfolio_value, 10000) as latest_portfolio_value,
                    COALESCE(ph.total_trades, 0) as total_trades,
                    COALESCE(ph.avg_gain_loss, 0) as avg_gain_loss,
                    COALESCE(ph.success_rate, 0) as success_rate
                FROM run_configurations rc
                LEFT JOIN (
                    SELECT 
                        config_hash,
                        MAX(total_portfolio_value) as latest_portfolio_value,
                        COUNT(*) as total_trades,
                        AVG(total_profit_loss) as avg_gain_loss,
                        AVG(CASE WHEN total_profit_loss > 0 THEN 1.0 ELSE 0.0 END) as success_rate
                    FROM portfolio_history 
                    GROUP BY config_hash
                ) ph ON rc.config_hash = ph.config_hash
                ORDER BY rc.last_used DESC
            """))
            
            # Trade comparison view
            conn.execute(text("""
                CREATE OR REPLACE VIEW trade_comparison AS
                SELECT 
                    config_hash,
                    COUNT(*) as total_decisions,
                    COUNT(CASE WHEN data::text LIKE '%buy%' THEN 1 END) as buy_decisions,
                    COUNT(CASE WHEN data::text LIKE '%sell%' THEN 1 END) as sell_decisions,
                    COUNT(CASE WHEN data::text LIKE '%hold%' THEN 1 END) as hold_decisions,
                    DATE_TRUNC('day', timestamp) as trade_date
                FROM trade_decisions 
                GROUP BY config_hash, DATE_TRUNC('day', timestamp)
                ORDER BY trade_date DESC, config_hash
            """))
            
            print("✅ Database migration completed successfully!")
            print("")
            print("📋 Summary of changes:")
            print("  - Added run_configurations table for tracking parallel configurations")
            print("  - Added config_hash column to all major tables")
            print("  - Updated holdings table structure for parallel runs")
            print("  - Created performance comparison views")
            print("")
            print("🚀 Your system now supports parallel runs with different configurations!")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False
    
    return True

def verify_migration():
    """Verify that migration was successful"""
    print("🔍 Verifying migration...")
    
    try:
        with engine.connect() as conn:
            # Check run_configurations table
            result = conn.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'run_configurations'"))
            if result.fetchone()[0] == 0:
                print("❌ run_configurations table not found")
                return False
            
            # Check some key tables have config_hash
            key_tables = ["summaries", "holdings", "trade_decisions"]
            for table in key_tables:
                try:
                    result = conn.execute(text(f"SELECT config_hash FROM {table} LIMIT 1"))
                    print(f"✅ {table} has config_hash column")
                except Exception:
                    print(f"❌ {table} missing config_hash column")
                    return False
            
            print("✅ Migration verification successful!")
            return True
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

def main():
    """Main migration function"""
    print("=" * 60)
    print("D-AI-Trader Database Migration for Parallel Runs")
    print("=" * 60)
    
    if migrate_database():
        if verify_migration():
            print("🎉 Migration completed successfully!")
            print("")
            print("Next steps:")
            print("1. Start multiple instances with different configurations:")
            print("   ./start_d_ai_trader.sh -p 8080 -m gpt-4.1 -v auto -t simulation")
            print("   ./start_d_ai_trader.sh -p 8081 -m gpt-5 -v auto -t simulation")
            print("   ./start_d_ai_trader.sh -p 8082 -m gpt-4.1 -v v4 -t real_world")
            print("")
            print("2. Each will have its own configuration hash and isolated data")
            print("3. Use the dashboard to compare performance between configurations")
            return 0
        else:
            print("❌ Migration verification failed")
            return 1
    else:
        print("❌ Migration failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
