#!/usr/bin/env python3
"""
Test the GPT-4o vision API to debug why it's not seeing images
"""
import os
import base64
import json
from dotenv import load_dotenv
import openai

load_dotenv(override=True)

api_key = os.getenv("OPENAI_API_KEY")
openai.api_key = api_key

# Find a recent screenshot
screenshots_dir = "/Users/adobi/d-ai-trader/screenshots"
test_image = None

# Look for recent CNBC screenshot
import glob
patterns = [
    f"{screenshots_dir}/**/Agent_CNBC_1.png",
    f"{screenshots_dir}/*/Agent_CNBC_1.png"
]

for pattern in patterns:
    files = glob.glob(pattern, recursive=True)
    if files:
        test_image = sorted(files)[-1]  # Get most recent
        break

if not test_image:
    print("❌ No test image found!")
    print(f"Looking in: {screenshots_dir}")
    exit(1)

print(f"✅ Found test image: {test_image}")
print(f"Image size: {os.path.getsize(test_image)} bytes")

# Test 1: Basic vision API call
print("\n" + "="*60)
print("TEST 1: Basic GPT-4o Vision API Call")
print("="*60)

with open(test_image, "rb") as img_file:
    image_bytes = img_file.read()
encoded_image = base64.b64encode(image_bytes).decode("utf-8")

print(f"Encoded image length: {len(encoded_image)} chars")

messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "What financial news headlines can you see in this image? List the top 3."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{encoded_image}"
                }
            }
        ]
    }
]

try:
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_completion_tokens=500
    )
    
    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason
    
    print(f"\n✅ API call successful!")
    print(f"Finish reason: {finish_reason}")
    print(f"Response length: {len(content)} chars")
    print(f"\nResponse:\n{content}\n")
    
except Exception as e:
    print(f"\n❌ API call failed: {e}")
    import traceback
    traceback.print_exc()

# Test 2: With system message (like our actual code)
print("\n" + "="*60)
print("TEST 2: With System Message (Like Production)")
print("="*60)

messages_with_system = [
    {
        "role": "system",
        "content": "You are a financial news analyzer. Extract key information from images."
    },
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "Analyze this financial news screenshot and list the top headlines you can see."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{encoded_image}"
                }
            }
        ]
    }
]

try:
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages_with_system,
        max_completion_tokens=500,
        temperature=0.3
    )
    
    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason
    
    print(f"\n✅ API call successful!")
    print(f"Finish reason: {finish_reason}")
    print(f"Response length: {len(content)} chars")
    print(f"\nResponse:\n{content}\n")
    
except Exception as e:
    print(f"\n❌ API call failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Test complete!")
print("="*60)

