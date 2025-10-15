#!/usr/bin/env python3
"""
Test the actual config.py ask_openai method to see what messages it sends
"""
import os
import sys
from dotenv import load_dotenv

# Setup environment
load_dotenv(override=True)
os.environ.setdefault("DAI_TRADER_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set model to gpt-4o for testing
os.environ["DAI_GPT_MODEL"] = "gpt-4o"

from config import PromptManager, openai, session, set_gpt_model
import glob

set_gpt_model("gpt-4o")

# Find a recent screenshot
screenshots_dir = "/Users/adobi/d-ai-trader/screenshots"
test_images = []

patterns = [
    f"{screenshots_dir}/**/Agent_CNBC_*.png",
]

for pattern in patterns:
    files = glob.glob(pattern, recursive=True)
    if files:
        # Get 2 most recent
        test_images = sorted(files)[-2:]
        break

if not test_images:
    print("❌ No test images found!")
    exit(1)

print(f"✅ Found {len(test_images)} test images:")
for img in test_images:
    print(f"  - {img}")

# Create PromptManager and test
pm = PromptManager(client=openai, session=session)

print("\n" + "="*60)
print("Testing config.py ask_openai with vision")
print("="*60)

# Test with actual prompt
test_prompt = """Analyze this financial news webpage screenshot.

Extract the following information in JSON format:
{
  "headlines": ["headline 1", "headline 2", "headline 3"],
  "insights": "Brief summary of key trading insights"
}"""

test_system = "You are a financial analysis assistant. Extract key information from news screenshots."

try:
    result = pm.ask_openai(
        prompt=test_prompt,
        system_prompt=test_system,
        agent_name="TestAgent",
        image_paths=test_images,
        max_retries=1
    )
    
    print(f"\n✅ Success!")
    print(f"Result type: {type(result)}")
    print(f"Result: {result}")
    
except Exception as e:
    print(f"\n❌ Failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Test complete!")
print("="*60)

