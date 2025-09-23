#!/usr/bin/env python3
"""
Test both GPT-4.1 and GPT-5 models to ensure parsing works correctly
"""
import os
import json
from config import PromptManager, session, openai, set_gpt_model, GPT_MODEL

def test_model_response(model_name):
    """Test a specific model's response format"""
    
    # Set the model
    set_gpt_model(model_name)
    print(f"\n{'='*60}")
    print(f"Testing model: {GPT_MODEL}")
    print('='*60)
    
    # Create prompt manager
    prompt_manager = PromptManager(client=openai, session=session)
    
    # Test prompt that should return an array
    test_prompt = """You are a day trading AI. Current portfolio: $10000 cash, no holdings.
    
News: Tech stocks are up. NVDA showing strength.

Make a trading decision.

CRITICAL: Respond ONLY with valid JSON array like this:
[{"action": "buy", "ticker": "NVDA", "amount_usd": 2000, "reason": "Tech momentum"}]

No text, just JSON array starting with [ and ending with ]"""

    test_system = "You are a trading agent. Always respond in valid JSON array format only."
    
    print("Sending request...")
    
    # Call the AI
    response = prompt_manager.ask_openai(
        test_prompt,
        test_system,
        agent_name="TestDecider"
    )
    
    print(f"\n📊 Response type: {type(response)}")
    print(f"📄 Raw response:\n{json.dumps(response, indent=2) if isinstance(response, (dict, list)) else str(response)}")
    
    # Test the conversion logic from decider_agent.py
    ai_response = response
    
    # This is the logic from decider_agent.py
    if isinstance(ai_response, dict):
        # Check if it's an error response first
        if 'error' in ai_response:
            print(f"\n❌ AI returned error: {ai_response.get('error')}")
            ai_response = []
        else:
            # Convert single dict to list (GPT-5 often returns single dict instead of array)
            print(f"\n📦 Converting single decision dict to list format")
            ai_response = [ai_response]
    elif not isinstance(ai_response, list):
        print(f"\n⚠️  Unexpected response type: {type(ai_response)}, converting to list")
        ai_response = [ai_response] if ai_response else []
    
    # Check final format
    print(f"\n✅ Final format after conversion:")
    print(f"   Type: {type(ai_response)}")
    print(f"   Is list: {isinstance(ai_response, list)}")
    if isinstance(ai_response, list) and len(ai_response) > 0:
        print(f"   First item type: {type(ai_response[0])}")
        if isinstance(ai_response[0], dict):
            print(f"   First item keys: {ai_response[0].keys()}")
            print(f"   Valid decision: {'action' in ai_response[0] and 'ticker' in ai_response[0]}")
    
    return ai_response

def main():
    print("Testing both GPT-4.1 and GPT-5 models...")
    print("Current API key status:", "Valid" if os.getenv('OPENAI_API_KEY', '').startswith('sk-') else "Invalid")
    
    # Test GPT-4.1
    result_gpt4 = test_model_response("gpt-4.1")
    
    # Test GPT-5-mini
    result_gpt5 = test_model_response("gpt-5-mini")
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    # Check GPT-4.1
    if isinstance(result_gpt4, list) and len(result_gpt4) > 0:
        if isinstance(result_gpt4[0], dict) and 'action' in result_gpt4[0]:
            print("✅ GPT-4.1: Working correctly - returns proper trading decisions")
        else:
            print("⚠️  GPT-4.1: Returns list but missing required fields")
    else:
        print("❌ GPT-4.1: Not working - returns invalid format")
    
    # Check GPT-5
    if isinstance(result_gpt5, list) and len(result_gpt5) > 0:
        if isinstance(result_gpt5[0], dict) and 'action' in result_gpt5[0]:
            print("✅ GPT-5-mini: Working correctly - returns proper trading decisions")
        else:
            print("⚠️  GPT-5-mini: Returns list but missing required fields")
    else:
        print("❌ GPT-5-mini: Not working - returns invalid format")
    
    print("\n🎯 Both models should now work with the fix applied!")

if __name__ == "__main__":
    main()
