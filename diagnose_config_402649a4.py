#!/usr/bin/env python3
"""
Diagnostic script for configuration 402649a4
"""

import os
import json
from feedback_agent import TradeOutcomeTracker
from config import get_current_config_hash, engine
from sqlalchemy import text

def diagnose_config_402649a4():
    """Diagnose configuration 402649a4"""
    print("🔍 Diagnosing Configuration 402649a4")
    print("=" * 60)
    
    # Set the configuration hash
    os.environ['CURRENT_CONFIG_HASH'] = '402649a4'
    
    tracker = TradeOutcomeTracker()
    
    # Step 1: Check current configuration
    config_hash = get_current_config_hash()
    print(f"📋 Current config hash: {config_hash}")
    
    # Step 2: Check if feedback exists
    print("\n📊 Checking feedback database entries...")
    with engine.connect() as conn:
        feedback_result = conn.execute(text("""
            SELECT analysis_timestamp, total_trades_analyzed, success_rate, 
                   summarizer_feedback, decider_feedback
            FROM agent_feedback 
            WHERE config_hash = :config_hash
            ORDER BY analysis_timestamp DESC 
            LIMIT 3
        """), {"config_hash": config_hash}).fetchall()
        
        if feedback_result:
            print(f"✅ Found {len(feedback_result)} feedback entries")
            latest = feedback_result[0]
            print(f"   Latest: {latest.analysis_timestamp}: {latest.total_trades_analyzed} trades, {latest.success_rate*100:.1f}% success")
            
            # Check feedback content
            summarizer_fb = latest.summarizer_feedback
            decider_fb = latest.decider_feedback
            
            print(f"   Summarizer feedback exists: {bool(summarizer_fb and summarizer_fb != 'null')}")
            print(f"   Decider feedback exists: {bool(decider_fb and decider_fb != 'null')}")
            
            if summarizer_fb and summarizer_fb != 'null':
                print(f"   Summarizer preview: {str(summarizer_fb)[:80]}...")
            if decider_fb and decider_fb != 'null':
                print(f"   Decider preview: {str(decider_fb)[:80]}...")
                
        else:
            print("❌ No feedback entries found for this config!")
    
    # Step 3: Check prompt versions
    print("\n📝 Checking prompt versions in database...")
    with engine.connect() as conn:
        prompt_result = conn.execute(text("""
            SELECT agent_type, version, description, is_active, created_at
            FROM prompt_versions
            WHERE config_hash = :config_hash
            ORDER BY agent_type, version DESC
        """), {"config_hash": config_hash}).fetchall()
        
        if prompt_result:
            print(f"✅ Found {len(prompt_result)} prompt versions")
            current_agent = None
            for row in prompt_result:
                if row.agent_type != current_agent:
                    print(f"\n   {row.agent_type}:")
                    current_agent = row.agent_type
                status = "🟢 ACTIVE" if row.is_active else "⚪ inactive"
                print(f"     v{row.version}: {status}")
                print(f"       Created: {row.created_at}")
                print(f"       Description: {row.description}")
        else:
            print("❌ No prompt versions found for this config!")
            
    # Step 4: Check for recent trades
    print("\n💼 Checking recent trades...")
    with engine.connect() as conn:
        trades_result = conn.execute(text("""
            SELECT COUNT(*) as trade_count
            FROM trade_outcomes
            WHERE config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchone()
        
        print(f"Total trades for this config: {trades_result.trade_count}")
        
        # Check recent trades
        recent_trades = conn.execute(text("""
            SELECT ticker, sell_timestamp, gain_loss_percentage, outcome_category
            FROM trade_outcomes
            WHERE config_hash = :config_hash
            ORDER BY sell_timestamp DESC
            LIMIT 5
        """), {"config_hash": config_hash}).fetchall()
        
        if recent_trades:
            print("Recent trades:")
            for trade in recent_trades:
                print(f"   {trade.ticker}: {trade.gain_loss_percentage:.2%} ({trade.outcome_category}) - {trade.sell_timestamp}")
        else:
            print("No recent trades found")
    
    print("\n" + "=" * 60)
    print("🎯 Analysis complete!")
    
    # Recommendations
    if not feedback_result:
        print("\n💡 ISSUE: No feedback found")
        print("   - The feedback agent may not have run yet")
        print("   - Or there may not be enough trades to analyze")
    elif not prompt_result:
        print("\n💡 ISSUE: No prompt versions found")
        print("   - Need to initialize baseline prompts for this config")
    elif len(prompt_result) == 2 and all(p.version == 0 for p in prompt_result):
        print("\n💡 ISSUE: Only v0 prompts exist")
        print("   - Auto-update mechanism may not be working")
        print("   - Can manually trigger prompt update")

if __name__ == "__main__":
    diagnose_config_402649a4()
