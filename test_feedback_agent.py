#!/usr/bin/env python3
"""
Test the feedback agent functionality
"""
import os
from feedback_agent import TradeOutcomeTracker
from config import get_current_config_hash, set_gpt_model, set_prompt_version_mode

def test_feedback_agent():
    """Test if feedback agent is working and creating new prompts"""
    
    # Set configuration to match what's on the dashboard
    set_gpt_model("gpt-4.1")
    set_prompt_version_mode("auto")
    
    # Set the config hash to match the dashboard
    os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'
    
    print(f"Testing Feedback Agent for config: {get_current_config_hash()}")
    print("="*60)
    
    # Initialize feedback tracker
    tracker = TradeOutcomeTracker()
    
    # Check current prompts
    print("\n📋 Current Active Prompts:")
    summarizer_prompt = tracker.get_active_prompt('SummarizerAgent')
    decider_prompt = tracker.get_active_prompt('DeciderAgent')
    
    if summarizer_prompt:
        print(f"  SummarizerAgent: v{summarizer_prompt.get('version', 'unknown')}")
    else:
        print("  SummarizerAgent: No active prompt found")
    
    if decider_prompt:
        print(f"  DeciderAgent: v{decider_prompt.get('version', 'unknown')}")
    else:
        print("  DeciderAgent: No active prompt found")
    
    # Get latest feedback
    print("\n📊 Latest Feedback:")
    latest_feedback = tracker.get_latest_feedback()
    if latest_feedback:
        print(f"  Success Rate: {latest_feedback.get('success_rate', 0):.1%}")
        print(f"  Avg Profit: {latest_feedback.get('avg_profit_percentage', 0):.2%}")
        print(f"  Total Trades: {latest_feedback.get('total_trades_analyzed', 0)}")
    else:
        print("  No feedback found")
    
    # Try to analyze recent outcomes
    print("\n🔄 Running Feedback Analysis...")
    try:
        result = tracker.analyze_recent_outcomes(days_back=30)
        if result:
            print(f"  Analysis completed!")
            if 'feedback_id' in result:
                print(f"  Feedback ID: {result['feedback_id']}")
            if 'feedback' in result:
                feedback = result['feedback']
                if isinstance(feedback, dict):
                    print(f"  Generated feedback with {len(feedback)} insights")
                    if 'summarizer_feedback' in feedback:
                        print(f"  Summarizer feedback: {feedback['summarizer_feedback'][:100]}...")
                    if 'decider_feedback' in feedback:
                        print(f"  Decider feedback: {feedback['decider_feedback'][:100]}...")
        else:
            print("  No analysis result")
    except Exception as e:
        print(f"  Error during analysis: {e}")
    
    # Check prompt history to see if new versions were created
    print("\n📚 Prompt History (last 5 versions):")
    from sqlalchemy import text
    from config import engine
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT agent_type, version, is_active, created_at, created_by
            FROM prompt_versions
            WHERE config_hash = :config_hash
            ORDER BY created_at DESC
            LIMIT 10
        """), {"config_hash": '9913d59e'})
        
        for row in result:
            active = "✓" if row.is_active else " "
            print(f"  [{active}] {row.agent_type}: v{row.version} - {row.created_at.strftime('%Y-%m-%d %H:%M')} by {row.created_by}")
    
    # Check if we're in AUTO mode
    print("\n🔧 Configuration Mode:")
    from config import get_prompt_version_config
    config = get_prompt_version_config()
    print(f"  Mode: {config['mode']}")
    if config['forced_version']:
        print(f"  Forced Version: v{config['forced_version']}")
    
    # Check if AUTO mode should be creating new prompts
    if config['mode'] == 'auto':
        print("\n✅ System is in AUTO mode - should create new prompts from feedback")
    else:
        print("\n⚠️  System is in FIXED mode - won't create new prompts automatically")

if __name__ == "__main__":
    test_feedback_agent()
