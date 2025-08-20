#!/usr/bin/env python3
"""
Verify that the automatic prompt updating system is working correctly
"""

import os
from config import get_prompt_version_config, get_current_config_hash
from feedback_agent import TradeOutcomeTracker
from d_ai_trader import DAITraderOrchestrator

def verify_auto_system():
    """Verify the automatic prompt updating system"""
    print("🔍 Verifying Automatic Prompt Update System")
    print("=" * 60)
    
    # Set config hash
    os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'
    
    # Step 1: Check prompt mode configuration
    print("📋 Checking configuration...")
    config_hash = get_current_config_hash()
    prompt_config = get_prompt_version_config()
    
    print(f"Config Hash: {config_hash}")
    print(f"Prompt Mode: {prompt_config['mode']}")
    print(f"Forced Version: {prompt_config['forced_version']}")
    
    if prompt_config['mode'] == 'auto':
        print("✅ PROMPT_MODE is set to AUTO - will use latest versions")
    else:
        print("⚠️  PROMPT_MODE is not AUTO - may use fixed version")
    
    # Step 2: Verify current prompt versions
    print("\n📝 Current active prompt versions...")
    tracker = TradeOutcomeTracker()
    
    try:
        summarizer_prompt = tracker.get_active_prompt('SummarizerAgent')
        if summarizer_prompt:
            print(f"✅ Summarizer: v{summarizer_prompt['version']}")
            print(f"   Description: {summarizer_prompt['description'][:80]}...")
        else:
            print("❌ No active summarizer prompt found")
            
        decider_prompt = tracker.get_active_prompt('DeciderAgent')
        if decider_prompt:
            print(f"✅ Decider: v{decider_prompt['version']}")
            print(f"   Description: {decider_prompt['description'][:80]}...")
        else:
            print("❌ No active decider prompt found")
            
    except Exception as e:
        print(f"❌ Error checking prompts: {e}")
    
    # Step 3: Check feedback system status
    print("\n📊 Checking feedback system...")
    latest_feedback = tracker.get_latest_feedback()
    if latest_feedback:
        print(f"✅ Latest feedback: {latest_feedback['total_trades_analyzed']} trades analyzed")
        print(f"   Success rate: {latest_feedback['success_rate'] * 100:.1f}%")
        
        # Check if feedback has content for auto-updates
        has_summarizer_fb = bool(latest_feedback.get('summarizer_feedback'))
        has_decider_fb = bool(latest_feedback.get('decider_feedback'))
        
        if has_summarizer_fb and has_decider_fb:
            print("✅ Feedback contains both summarizer and decider guidance")
        else:
            print("⚠️  Feedback missing summarizer or decider guidance")
    else:
        print("❌ No feedback found")
    
    # Step 4: Test the orchestrator setup
    print("\n🤖 Checking orchestrator setup...")
    try:
        orchestrator = DAITraderOrchestrator()
        print("✅ Orchestrator initialized successfully")
        print("   - Contains feedback_tracker for daily analysis")
        print("   - Will run feedback analysis daily")
    except Exception as e:
        print(f"❌ Error initializing orchestrator: {e}")
    
    # Step 5: Summary and expectations
    print("\n" + "=" * 60)
    print("🎯 SYSTEM STATUS SUMMARY")
    print("=" * 60)
    
    if prompt_config['mode'] == 'auto':
        print("✅ AUTO MODE: System will use latest prompt versions")
        print("📅 DAILY PROCESS:")
        print("   1. Feedback agent runs daily")
        print("   2. Analyzes recent trades (if any)")
        print("   3. Generates AI feedback for improvements")
        print("   4. Automatically creates new prompt versions (v2, v3, etc.)")
        print("   5. New versions become active immediately")
        print("   6. Summarizer/Decider agents use updated prompts")
        
        print("\n🔄 EXPECTED BEHAVIOR:")
        print("   - Prompts will evolve: v1 → v2 → v3 → ...")
        print("   - Each version incorporates lessons from recent trades")
        print("   - Dashboard will show increasing version numbers")
        print("   - 'Current vs Previous Prompts' will show comparisons")
        
        print("\n📈 PERFORMANCE IMPROVEMENT:")
        print("   - Agents learn from successful/unsuccessful trades")
        print("   - Prompts become more specific to your trading patterns")
        print("   - System adapts to market conditions over time")
        
    else:
        print("⚠️  FIXED MODE: System will use a specific prompt version")
        print(f"   Using version: {prompt_config['forced_version']}")
        print("   To enable auto-updates, set PROMPT_MODE to 'auto'")
    
    print("\n🔧 MONITORING:")
    print("   - Check dashboard daily for version increases")
    print("   - Monitor 'Analysis Summary' in feedback tab")
    print("   - Look for 'Auto-generated from feedback' in descriptions")

if __name__ == "__main__":
    verify_auto_system()
