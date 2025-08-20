#!/usr/bin/env python3
"""
Test that configuration hash is preserved when running feedback agent
"""

import os
from d_ai_trader import DAITraderOrchestrator
from config import get_current_config_hash

def test_config_preservation():
    """Test that config hash is preserved during feedback agent run"""
    print("🔧 Testing Configuration Hash Preservation")
    print("=" * 60)
    
    # Set a test configuration
    test_config = "402649a4"
    os.environ['CURRENT_CONFIG_HASH'] = test_config
    
    print(f"📋 Initial config hash: {get_current_config_hash()}")
    
    # Create orchestrator and run feedback agent
    orchestrator = DAITraderOrchestrator()
    
    print("🤖 Running feedback agent...")
    try:
        orchestrator.run_feedback_agent()
        print("✅ Feedback agent completed")
    except Exception as e:
        print(f"⚠️  Feedback agent error: {e}")
    
    # Check if config hash is preserved
    final_config = get_current_config_hash()
    print(f"📋 Final config hash: {final_config}")
    
    if final_config == test_config:
        print("✅ SUCCESS: Configuration hash preserved!")
        print("🎯 The dashboard will maintain the same configuration view")
    else:
        print("❌ FAILURE: Configuration hash changed!")
        print(f"   Expected: {test_config}")
        print(f"   Got: {final_config}")
    
    print("\n" + "=" * 60)
    print("🎯 Test complete!")

if __name__ == "__main__":
    test_config_preservation()
