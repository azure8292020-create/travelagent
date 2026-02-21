import os
import sys

# MOCK ENVIRONMENT VARIABLES (Must be done BEFORE importing lambda_function)
# These simulate what Docker/Lambda would provide
os.environ['RAPIDAPI_KEY_PATH'] = "/flights/rapidapi_key"
os.environ['OPENAI_API_KEY_PATH'] = "/flights/openai_key" # or Gemini path
os.environ['SEARCH_TABLE'] = "ActiveSearches"
os.environ['SNS_TOPIC_ARN'] = "arn:aws:sns:..."

# Now it is safe to import
import lambda_function # Import the module first to patch it
from lambda_function import call_skyscanner, resolve_entity_id, evaluate_flight_deal

# --- USER: PASTE YOUR KEYS HERE FOR LOCAL TESTING ---
MY_RAPIDAPI_KEY = "" 
MY_GEMINI_KEY = ""

# Monkey Patch: Force the lambda module to use these keys instead of SSM
lambda_function.RAPIDAPI_KEY = MY_RAPIDAPI_KEY
lambda_function.GEMINI_API_KEY = MY_GEMINI_KEY

# Re-initialize Gemini with the new key if present
if MY_GEMINI_KEY and "PASTE" not in MY_GEMINI_KEY:
    import google.generativeai as genai
    genai.configure(api_key=MY_GEMINI_KEY)
    # Falling back to 'gemini-pro' as 1.5-flash threw a 404 for this key
    # DEBUG: List available models to find the right name
    print("DEBUG: Listing available Gemini Models for this Key...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f" - {m.name}")
            
    # Attempt to use the first available 'gemini' model if pro fails?
    # For now, let's just stick to pro and see the list output.
    lambda_function.gemini_model = genai.GenerativeModel('gemini-flash-latest') 
    print("DEBUG: Gemini Client Re-Initialized for Local Test")

import time # Import time for rate limiting

test_search = {
    "src": "IAD",
    "dst": "BLR",
    "date": "2026-02-07",  # Ensure this is a valid future date
    "return": "2026-02-18",
    "adults": 1,
    "contact": "1234567890",
    "username": "TestUser",
    "notes": "No long layovers"
}

# Ensure Environment Variables are set (or mock them)
# You need to export RAPIDAPI_KEY_PATH, etc. or set them here if your code reads env vars directly.
# However, your code uses SSM. If you have valid AWS credentials in your terminal, it might just work.
# If not, you might need to mock get_ssm_parameter.

print("--- 1. Testing Entity Resolution ---")
origin_id = resolve_entity_id(test_search['src'])
time.sleep(1.5) # Avoid RapidAPI 429 Rate Limit
dest_id = resolve_entity_id(test_search['dst'])
time.sleep(1.5) # Avoid RapidAPI 429 Rate Limit
print(f"Resolved IAD -> {origin_id}")
print(f"Resolved BLR -> {dest_id}")

if not origin_id or not dest_id:
    print("❌ Failed to resolve IDs. Check API Key or Internet.")
    exit(1)

print("\n--- 2. Testing Skyscanner API ---")
flight_result = call_skyscanner(test_search)
if flight_result:
    print(f"✅ Flight Found: {flight_result}")
else:
    print("❌ No flight found or API error.")

print("\n--- 3. Testing Gemini AI Analysis (Optional) ---")
if flight_result:
    should_send, msg = evaluate_flight_deal(flight_result, test_search, test_search['notes'])
    print(f"AI Decision: Send={should_send}")
    print(f"AI Message: {msg}")
