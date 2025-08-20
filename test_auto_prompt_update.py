#!/usr/bin/env python3
"""
Test the automatic prompt update mechanism directly
"""

import os
import json
from feedback_agent import TradeOutcomeTracker
from config import get_current_config_hash

def test_auto_prompt_update():
    """Test why _auto_generate_prompts_from_feedback isn't working"""
    print("🧪 Testing Automatic Prompt Update Mechanism")
    print("=" * 60)
    
    # Set the configuration hash
    os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'
    
    tracker = TradeOutcomeTracker()
    
    # Step 1: Get the latest feedback
    print("📊 Getting latest feedback...")
    latest_feedback = tracker.get_latest_feedback()
    
    if not latest_feedback:
        print("❌ No feedback found!")
        return
        
    print(f"✅ Found feedback with {latest_feedback.get('total_trades_analyzed')} trades")
    
    # Step 2: Check the feedback structure
    print("\n🔍 Analyzing feedback structure...")
    summarizer_fb = latest_feedback.get('summarizer_feedback')
    decider_fb = latest_feedback.get('decider_feedback')
    
    print(f"Summarizer feedback type: {type(summarizer_fb)}")
    print(f"Summarizer feedback empty?: {not bool(summarizer_fb)}")
    print(f"Summarizer feedback == 'null'?: {summarizer_fb == 'null'}")
    print(f"Summarizer feedback length: {len(str(summarizer_fb)) if summarizer_fb else 0}")
    
    print(f"Decider feedback type: {type(decider_fb)}")  
    print(f"Decider feedback empty?: {not bool(decider_fb)}")
    print(f"Decider feedback == 'null'?: {decider_fb == 'null'}")
    print(f"Decider feedback length: {len(str(decider_fb)) if decider_fb else 0}")
    
    # Step 3: Test the conditions in _auto_generate_prompts_from_feedback
    print(f"\n🔧 Testing auto-update conditions...")
    
    # Simulate the exact conditions from the method
    if summarizer_fb:
        print("✅ Summarizer feedback condition: PASSED")
    else:
        print("❌ Summarizer feedback condition: FAILED")
        
    if decider_fb:
        print("✅ Decider feedback condition: PASSED")
    else:
        print("❌ Decider feedback condition: FAILED")
    
    # Step 4: Try to manually call the auto-update method
    print(f"\n🚀 Manually testing prompt generation...")
    
    try:
        # Create a fake feedback structure to test
        test_feedback = {
            'summarizer_feedback': summarizer_fb,
            'decider_feedback': decider_fb,
            'timing_patterns': 'Test timing patterns',
            'risk_management': 'Test risk management',
            'sector_insights': 'Test sector insights'
        }
        
        print("Calling _auto_generate_prompts_from_feedback...")
        
        # Call the private method directly
        tracker._auto_generate_prompts_from_feedback(test_feedback, 999)
        
        print("✅ Auto-generate method completed without errors")
        
        # Check if new prompts were created
        print("\n🔍 Checking for new prompt versions...")
        new_summarizer = tracker.get_active_prompt('SummarizerAgent')
        if new_summarizer and new_summarizer['version'] > 0:
            print(f"✅ NEW Summarizer prompt created: v{new_summarizer['version']}")
        else:
            print("❌ No new summarizer prompt created")
            
        new_decider = tracker.get_active_prompt('DeciderAgent')
        if new_decider and new_decider['version'] > 0:
            print(f"✅ NEW Decider prompt created: v{new_decider['version']}")
        else:
            print("❌ No new decider prompt created")
            
    except Exception as e:
        print(f"❌ Error in auto-generate method: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("🎯 Test complete!")

if __name__ == "__main__":
    test_auto_prompt_update()
