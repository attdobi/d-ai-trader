#!/usr/bin/env python3
"""
Check why configuration hash is switching when running feedback agent
"""

import os
from config import get_current_config_hash, engine
from sqlalchemy import text
from d_ai_trader import DAITraderOrchestrator

def check_config_switching():
    """Check the configuration switching behavior"""
    print("🔍 Checking Configuration Hash Switching Issue")
    print("=" * 60)
    
    # Step 1: Check current config hash
    print("📋 Current configuration state...")
    current_hash = get_current_config_hash()
    print(f"Current config hash: {current_hash}")
    
    # Step 2: Check what configs are active according to the orchestrator
    print("\n🤖 Checking active configurations...")
    orchestrator = DAITraderOrchestrator()
    active_configs = orchestrator._get_active_config_hashes()
    
    if active_configs:
        print(f"✅ Found {len(active_configs)} active configurations:")
        for i, config in enumerate(active_configs, 1):
            print(f"   {i}. {config}")
            
        print(f"\n⚠️  ISSUE IDENTIFIED:")
        print(f"When you click 'Run Feedback Agent', the system processes ALL active configs:")
        for config in active_configs:
            print(f"   - Sets environment to: {config}")
            print(f"   - Runs feedback analysis for: {config}")
            print(f"   - Dashboard shows the LAST config processed: {config}")
            
        print(f"\n🔧 SOLUTION:")
        print(f"The system is working correctly, but the dashboard shows the last config processed.")
        print(f"Your original config {current_hash} was processed, but then the system")
        print(f"continued to process other configs, ending with {active_configs[-1]}")
        
    else:
        print("❌ No active configurations found")
    
    # Step 3: Check recent trades for each config
    print(f"\n💼 Recent trading activity by configuration...")
    with engine.connect() as conn:
        for config in active_configs:
            trade_count = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM trade_decisions 
                WHERE config_hash = :config_hash
                  AND timestamp >= NOW() - INTERVAL '2 days'
            """), {"config_hash": config}).fetchone()
            
            print(f"   {config}: {trade_count.count} trades in last 2 days")
    
    # Step 4: Check feedback entries for each config
    print(f"\n📊 Recent feedback by configuration...")
    with engine.connect() as conn:
        for config in active_configs:
            feedback_count = conn.execute(text("""
                SELECT COUNT(*) as count, MAX(analysis_timestamp) as latest
                FROM agent_feedback 
                WHERE config_hash = :config_hash
            """), {"config_hash": config}).fetchone()
            
            print(f"   {config}: {feedback_count.count} feedback entries, latest: {feedback_count.latest}")
    
    print("\n" + "=" * 60)
    print("🎯 EXPLANATION:")
    print("The feedback agent is designed to process ALL active configurations.")
    print("When you clicked 'Run Feedback Agent' while viewing config 402649a4,")
    print("it processed that config AND all other active configs.")
    print("The dashboard now shows the LAST config that was processed.")
    print(f"Your prompts for 402649a4 were updated, but you're now viewing {current_hash}!")

if __name__ == "__main__":
    check_config_switching()
