#!/usr/bin/env python3
"""
Test GPT-5 JSON Response Issues
"""
import os
import json
from config import PromptManager, session, openai, GPT_MODEL, set_gpt_model
from prompt_manager import get_active_prompt

def test_decider_response():
    """Test what the decider agent is actually returning"""
    
    # Set to gpt-5-mini to match your current setup
    set_gpt_model("gpt-5-mini")
    print(f"Testing with model: {GPT_MODEL}")
    
    # Create prompt manager
    prompt_manager = PromptManager(client=openai, session=session)
    
    # Get the prompt that's being used
    try:
        prompt_data = get_active_prompt("DeciderAgent")
        print(f"Using DeciderAgent prompt v{prompt_data['version']}")
    except:
        print("Could not load prompt")
        prompt_data = {
            "system_prompt": "You are a trading agent.",
            "user_prompt_template": "Make a decision. Return JSON: [{\"action\": \"hold\", \"ticker\": \"SPY\", \"amount_usd\": 0, \"reason\": \"test\"}]"
        }
    
    # Simple test prompt
    test_prompt = """You are a day trading AI. Current portfolio: $10000 cash, no holdings.
    
News: Tech stocks are up today. NVDA showing strength.

Make ONE trading decision.

CRITICAL: Respond ONLY with valid JSON array like this:
[{"action": "buy", "ticker": "NVDA", "amount_usd": 2000, "reason": "Tech momentum"}]

No text, just JSON array."""

    test_system = "You are a trading agent. Always respond in valid JSON format only."
    
    print("\n" + "="*50)
    print("Sending test request to GPT-5...")
    print("="*50)
    
    # Call the AI
    response = prompt_manager.ask_openai(
        test_prompt,
        test_system,
        agent_name="TestDecider"
    )
    
    print("\nRaw response type:", type(response))
    print("\nRaw response:")
    print(json.dumps(response, indent=2) if isinstance(response, (dict, list)) else str(response))
    
    # Check if it's parseable
    if isinstance(response, list):
        print("\n✅ Response is already a list (parsed successfully)")
        if len(response) > 0 and isinstance(response[0], dict):
            print("✅ First item is a dict with keys:", response[0].keys() if response else "empty")
    elif isinstance(response, dict):
        print("\n⚠️ Response is a dict, not a list")
        if "error" in response:
            print(f"❌ Error in response: {response.get('error')}")
    else:
        print(f"\n❌ Response is {type(response)}, not JSON")
    
    return response

if __name__ == "__main__":
    print("Testing GPT-5 JSON response handling...")
    result = test_decider_response()
    
    print("\n" + "="*50)
    print("DIAGNOSIS:")
    print("="*50)
    
    if isinstance(result, dict) and "error" in result:
        print("❌ The AI is returning error responses")
        print("Possible causes:")
        print("1. GPT-5 model having issues with JSON format")
        print("2. Prompt not clear enough about JSON requirement")
        print("3. Token limits being hit")
        
        print("\n🔧 SOLUTION:")
        print("1. Switch to gpt-4.1 model (more reliable)")
        print("2. Or switch prompt mode to 'auto' to evolve prompts")
        print("3. Run: ./start_d_ai_trader.sh -m gpt-4.1 -v auto")
    elif isinstance(result, list):
        print("✅ JSON parsing is working correctly")
        print("The issue might be elsewhere in the pipeline")
    else:
        print("❌ Response format is completely wrong")
        print("The model is not following JSON instructions")
