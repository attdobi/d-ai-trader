#!/usr/bin/env python3
"""
Diagnostic script to debug prompt updating for configuration 9913d59e
"""

import os
import json
from feedback_agent import TradeOutcomeTracker
from config import get_current_config_hash, engine
from sqlalchemy import text

def diagnose_prompt_updating():
    """Diagnose why prompts aren't updating automatically"""
    print("🔍 Diagnosing Prompt Update Issue for Configuration 9913d59e")
    print("=" * 60)
    
    # Set the configuration hash
    os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'
    
    tracker = TradeOutcomeTracker()
    
    # Step 1: Check current configuration
    config_hash = get_current_config_hash()
    print(f"📋 Current config hash: {config_hash}")
    
    # Step 2: Check database for feedback entries
    print("\n📊 Checking feedback database entries...")
    with engine.connect() as conn:
        feedback_result = conn.execute(text("""
            SELECT analysis_timestamp, total_trades_analyzed, success_rate, 
                   summarizer_feedback, decider_feedback
            FROM agent_feedback 
            WHERE config_hash = :config_hash
            ORDER BY analysis_timestamp DESC 
            LIMIT 5
        """), {"config_hash": config_hash}).fetchall()
        
        if feedback_result:
            print(f"✅ Found {len(feedback_result)} feedback entries")
            for i, row in enumerate(feedback_result):
                print(f"   {i+1}. {row.analysis_timestamp}: {row.total_trades_analyzed} trades, {row.success_rate*100:.1f}% success")
                
                # Check feedback content
                summarizer_fb = row.summarizer_feedback
                decider_fb = row.decider_feedback
                
                print(f"      Summarizer feedback type: {type(summarizer_fb)}")
                if summarizer_fb and summarizer_fb != 'null':
                    if isinstance(summarizer_fb, str) and len(summarizer_fb) > 10:
                        print(f"      Summarizer preview: {summarizer_fb[:80]}...")
                    else:
                        print(f"      Summarizer value: {summarizer_fb}")
                else:
                    print(f"      Summarizer feedback: EMPTY or NULL")
                    
                print(f"      Decider feedback type: {type(decider_fb)}")
                if decider_fb and decider_fb != 'null':
                    if isinstance(decider_fb, str) and len(decider_fb) > 10:
                        print(f"      Decider preview: {decider_fb[:80]}...")
                    else:
                        print(f"      Decider value: {decider_fb}")
                else:
                    print(f"      Decider feedback: EMPTY or NULL")
                print()
        else:
            print("❌ No feedback entries found for this config!")
    
    # Step 3: Check prompt versions in database
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
                print(f"     v{row.version}: {status} - {row.description}")
                print(f"       Created: {row.created_at}")
        else:
            print("❌ No prompt versions found for this config!")
    
    # Step 4: Test get_active_prompt function
    print("\n🔧 Testing get_active_prompt function...")
    try:
        summarizer_prompt = tracker.get_active_prompt('SummarizerAgent')
        if summarizer_prompt:
            print(f"✅ get_active_prompt returned: v{summarizer_prompt['version']}")
            print(f"   Description: {summarizer_prompt.get('description', 'No description')}")
        else:
            print("❌ get_active_prompt returned None for SummarizerAgent")
            
        # Try the old agent type too
        summarizer_prompt_old = tracker.get_active_prompt('summarizer')
        if summarizer_prompt_old:
            print(f"✅ get_active_prompt('summarizer') returned: v{summarizer_prompt_old['version']}")
        else:
            print("❌ get_active_prompt('summarizer') returned None")
            
    except Exception as e:
        print(f"❌ Error testing get_active_prompt: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 5: Check what the dashboard API returns
    print("\n🌐 Testing dashboard API calls...")
    try:
        from dashboard_server import app
        with app.test_client() as client:
            # Set the config hash in environment for the API call
            with app.test_request_context():
                os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'
                
                # Test the prompts API
                response = client.get('/api/prompts/SummarizerAgent')
                if response.status_code == 200:
                    data = response.get_json()
                    if data:
                        print(f"✅ Dashboard API found {len(data)} prompt versions")
                        for prompt in data[:3]:  # Show first 3
                            status = "🟢 ACTIVE" if prompt.get('is_active') else "⚪ inactive"
                            print(f"   v{prompt.get('prompt_version', 'unknown')}: {status}")
                    else:
                        print("❌ Dashboard API returned empty data")
                else:
                    print(f"❌ Dashboard API error: {response.status_code}")
                    
    except Exception as e:
        print(f"⚠️  Could not test dashboard API: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 Diagnosis complete!")
    
    # Step 6: Recommendations
    print("\n💡 RECOMMENDATIONS:")
    if not feedback_result:
        print("1. No feedback found - run: python run_feedback_analysis.py")
    elif not prompt_result:
        print("1. No prompts found - run: python initialize_prompts.py")
    else:
        print("1. Feedback and prompts exist - checking for update issues...")
        
        # Check if feedback has valid content
        has_valid_feedback = False
        if feedback_result:
            latest = feedback_result[0]
            if (latest.summarizer_feedback and latest.summarizer_feedback not in ['null', ''] and 
                latest.decider_feedback and latest.decider_feedback not in ['null', '']):
                has_valid_feedback = True
                
        if not has_valid_feedback:
            print("2. Feedback exists but may be empty/invalid - this prevents auto-updates")
            print("3. Try manual update: python force_prompt_update_9913d59e.py")
        else:
            print("2. Valid feedback exists - auto-update should work")
            print("3. Check for errors in system logs during feedback analysis")

if __name__ == "__main__":
    diagnose_prompt_updating()
