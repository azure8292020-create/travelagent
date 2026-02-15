import os
import random
import json
import time
import asyncio
import boto3
import requests
import google.generativeai as genai
from playwright.async_api import async_playwright
from playwright_stealth import stealth
import sys
      
search_path = sys.path
print(search_path)

# --- 1. INITIALIZATION & SECRETS ---
# Cached clients for reuse across Lambda warm starts
ssm = boto3.client('ssm')
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')

def get_ssm_parameter(name):
    """Retrieves decrypted secrets from AWS Parameter Store."""
    try:
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        print(f"Error fetching SSM parameter {name}: {e}")
        return None

# Load environment variables (Matches your previous setup)
RAPIDAPI_KEY = get_ssm_parameter(os.environ.get('RAPIDAPI_KEY_PATH'))
TABLE_NAME = os.environ.get('SEARCH_TABLE')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
GEMINI_API_KEY = get_ssm_parameter("/flights/gemini_key") # Hardcoded path or use env var

# Initialize Gemini Client
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Gemini 1.5 Flash is efficient and has a free tier
        gemini_model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
        print("DEBUG: Gemini Client Initialized")
    except Exception as e:
        print(f"WARNING: Failed to init Gemini: {e}")
else:
    print("WARNING: GEMINI_API_KEY not found in SSM. Smart filtering disabled.")

# --- 2b. LOGIC: LLM ANALYSIS ---
def evaluate_flight_deal(flight_data, user_profile, notes):
    """
    Uses Gemini to decide if a flight is worth sending and drafts the SMS.
    Also handles ERROR diagnosis.
    Returns: (bool: should_send, str: message_body)
    """
    if not gemini_model:
        return True, f"Alert: {flight_data}"

    # --- ERROR HANDLING PATH ---
    if "error" in flight_data:
        print(f"DEBUG: Asking Gemini to explain API Error: {flight_data['error']}")
        prompt = f"""
        You are a Backend Reliability Engineer. Use your knowledge to explain this API error.
        Error: "{flight_data['error']}"
        Request Context: {user_profile['src']} -> {user_profile['dst']} on {user_profile['date']}
        
        Write a short 1-sentence log suitable for an admin SMS explain what is likely wrong (e.g., 'API Key Invalid', 'No flights on this date', 'Rate Limit').
        """
        try:
            response = gemini_model.generate_content(prompt)
            # return TRUE so the user gets the error report log
            return True, f"SYSTEM ERROR: {response.text.strip()}"
        except:
            return True, f"SYSTEM ERROR: {flight_data['error']}"

    # --- HAPPY PATH ---
    if not notes:
        print(f"DEBUG: Skipping AI analysis (Gemini Active: {bool(gemini_model)}, Notes: {bool(notes)})")
        # Fallback: Always send if no LLM or no notes
        default_msg = (f"Flight Alert for {user_profile.get('username')}!\n"
                       f"Route: {user_profile['src']} -> {user_profile['dst']}\n"
                       f"Price: ${flight_data['price']}")
        return True, default_msg

    print(f"DEBUG: Asking Gemini to evaluate deal for {user_profile.get('contact')}")
    
    prompt = f"""
    You are a travel agent assistant. 
    User Preferences:
    - Route: {user_profile['src']} to {user_profile['dst']}
    - User Notes/Constraints: "{notes}"
    
    Flight Found:
    - Airline: {flight_data['airline']}
    - Price: ${flight_data['price']}
    
    Tasks:
    1. Does this flight strictly meet the user's notes? (e.g. if notes say 'no morning flights' and flight is morning, answer NO).
    2. Write a short, exciting SMS alert (max 160 chars) if it matches.
    
    Output JSON only: {{"match": true/false, "sms": "..."}}
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        raw_text = response.text.strip()
        print(f"DEBUG: Gemini Raw Response: {raw_text}")
        
        # CLEANUP: Remove markdown code blocks if present
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            
        result = json.loads(raw_text)
        return result.get("match", True), result.get("sms", "Deal found!")
    except Exception as e:
        print(f"ERROR: LLM API Call Failed: {e}")
        # Fail open (send the alert anyway)
        return True, f"Deal found! ${flight_data['price']} (AI analysis failed)"


# --- 2. LOGIC: PLAYWRIGHT SCRAPER ---
async def scrape_extra_details(url):
    """
    New logic for scraping site details (like Expedia/Google) 
    using the now-working Playwright container environment.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--single-process", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0...")
        page = await context.new_page()
        await stealth(page)
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            title = await page.title()
            return {"site_title": title, "status": "Success"}
        except Exception as e:
            print(f"Playwright Scraping Error: {e}")
            return None
        finally:
            await browser.close()

def resolve_entity_id(query):
    """
    Helper to resolve a SkyId/City to an EntityId (required by API).
    """
    # Corrected Endpoint based on 404 error
    # Fallback/Debug Dictionary (Since API auto-suggest path is elusive)
    # These are common Entity IDs for Skyscanner
    known_entities = {
        "IAD": "29475437", # Washington Dulles
        "BLR": "29475359", # Bengaluru
        "JFK": "29475432", # New York JFK
        "LHR": "29475430", # London Heathrow
        "DXB": "29475431"  # Dubai
    }
    
    if query.upper() in known_entities:
        print(f"DEBUG: Using Hardcoded ID for {query}")
        return known_entities[query.upper()]

    # If not in our mini-db, just return the SkyId and hope the API accepts it
    # or that the user enters the EntityId directly.
    print(f"DEBUG: Could not resolve {query}, using raw code.")
    return query

# --- 3. LOGIC: FLY-SCRAPER API (Replaces Skyscanner) ---
def call_skyscanner(search_data):
    """Calls Fly-Scraper via RapidAPI (New Endpoint provided by user)."""
    base_url = "https://fly-scraper.p.rapidapi.com/v2/flights/search-roundtrip"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "fly-scraper.p.rapidapi.com"
    }

    # Map DynamoDB keys to New API params
    # Docs: originSkyId, destinationSkyId, departureDate, returnDate, cabinClass, adults...
    querystring = {
        "originSkyId": search_data.get('src'),       # e.g. IAD
        "destinationSkyId": search_data.get('dst'),  # e.g. BLR
        "departureDate": search_data.get('date'),    # YYYY-MM-DD
        "returnDate": search_data.get('return'),     # YYYY-MM-DD
        "adults": search_data.get('adults', 1),
        "children": search_data.get('children', 0),
        "infants": search_data.get('infants', 0),
        "cabinClass": search_data.get('cabinClass', 'economy'),
        "currency": "USD",
        "locale": "en-US",
        "market": "US"
    }
    
    try:
        print(f"DEBUG: Calling Fly-Scraper API: {querystring}")
        response = requests.get(base_url, headers=headers, params=querystring)
        
        if response.status_code == 200:
            data = response.json()
            # print(f"DEBUG: RAW API RESPONSE: {str(data)[:500]}") # Debugging
            
            # PARSING LOGIC FOR FLY-SCRAPER
            # Usually: data -> data -> itineraries
            api_data = data.get('data', {})
            itineraries = api_data.get('itineraries', [])
            
            if itineraries:
                best_deal = itineraries[0]
                # Price parsing depends on API. Usually valid for this scraper:
                price_info = best_deal.get('price', {})
                price_scraped = price_info.get('formatted') or f"${price_info.get('raw')}"
                
                # Airline parsing
                legs = best_deal.get('legs', [])
                airline_Name = "Unknown"
                if legs:
                    carriers = legs[0].get('carriers', {}).get('marketing', [])
                    if carriers:
                        airline_Name = carriers[0].get('name')

                return {"price": price_scraped, "airline": airline_Name, "link": "N/A"}
            else:
                return {"error": "API Success but 0 flights found."}
        else:
            print(f"ERROR: API Failed: {response.text}")
            return {"error": f"API {response.status_code}: {response.text}"}

    except Exception as e:
        print(f"ERROR: API Function Exception: {e}")
        return {"error": f"Internal Error: {str(e)}"}

# --- 4. MAIN HANDLER ---
# --- 4. ACTION HANDLERS (Modular Stages) ---

def handle_send_otp(body, table):
    contact = body.get("contact")
    otp_code = f"{random.randint(100000, 999999)}"
    
    # Store OTP with short TTL
    table.put_item(Item={
        'contact': contact,
        'otp': otp_code,
        'ttl': int(time.time()) + 300
    })

    # Send SMS via SNS
    try:
        sns.publish(PhoneNumber=contact, Message=f"Your Flight Hunter verification code is: {otp_code}")
        print(f"DEBUG: OTP {otp_code} Sent to {contact} via SNS")
    except Exception as e:
        print(f"WARNING: SMS Failed: {e}. Returning Debug OTP.")
    
    return create_response(200, {"message": "OTP Sent", "debug_otp": otp_code})

async def handle_scrape_one(body):
    url = body.get("url")
    result = await scrape_extra_details(url)
    return create_response(200, result)

def handle_verify_otp(body, table):
    contact = body.get('contact')
    user_otp = body.get('otp')
    
    # Fetch stored OTP
    response = table.get_item(Key={'contact': contact})
    stored_item = response.get('Item')
    
    if not stored_item or str(stored_item.get('otp')) != str(user_otp):
        return create_response(403, {"message": "Invalid or expired OTP."})

    # Save Search Request
    item = {
        'contact': contact,
        'username': body.get('username', 'Guest'),
        'src': body.get('originSkyId'),
        'dst': body.get('destinationSkyId'),
        'date': body.get('departureDate'),
        'return': body.get('returnDate'),
        'adults': body.get('adults', 1),
        'children': body.get('children', 0),
        'infants': body.get('infants', 0),
        'cabinClass': body.get('cabinClass', 'economy'),
        'stops': body.get('stops', 'direct,1stop,2stops'),
        'notes': body.get('notes', ''), # Crucial for Gemini
        'timestamp': int(time.time()),
        'ttl': int(time.time()) + (86400 * 7) # Expire in 7 days
    }
    
    table.put_item(Item=item)
    print(f"DEBUG: OTP Valid. Saved Search: {item}")
    return create_response(200, {"message": "Verified! Search active."})

def handle_analyze_request(body):
    analysis = analyze_flight_request(body)
    return create_response(200, analysis)

def handle_polling(table):
    active_searches = table.scan()['Items']
    print(f"POLLING: Found {len(active_searches)} active searches.")

    for search in active_searches:
        sky_result = call_skyscanner(search)
        
        if sky_result:
            should_send, msg_body = evaluate_flight_deal(sky_result, search, search.get('notes', ''))
            
            if should_send:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN, 
                    Message=msg_body, 
                    Subject="Flight Hunter Alert"
                )
                print(f"Alert sent to {search.get('contact')}")
            else:
                print(f"Filtered by AI: {sky_result['price']}")

    return create_response(200, {"status": "Batch polling completed"})


# --- 5. MAIN ENTRY POINT ---
def lambda_handler(event, context):
    return asyncio.run(main_loop(event))

async def main_loop(event):
    print(f"DEBUG: Received event: {json.dumps(event)}")

    # 1. CORS Preflight
    if event.get("httpMethod") == "OPTIONS":
        return create_response(200, {"message": "CORS OK"})

    table = dynamodb.Table(TABLE_NAME)
    
    # 2. Logic Router
    if "body" in event:
        try:
            body = json.loads(event["body"])
            action = body.get("action")
            
            if action == "SEND_OTP":        return handle_send_otp(body, table)
            elif action == "SCRAPE_ONE":    return await handle_scrape_one(body)
            elif action == "VERIFY_OTP":    return handle_verify_otp(body, table)
            elif action == "ANALYZE_REQUEST": return handle_analyze_request(body)
            else: return create_response(400, {"message": "Invalid action"})
            
        except Exception as e:
            print(f"CRITICAL ERROR: {str(e)}")
            return create_response(500, {"message": str(e)})

    # 3. Scheduled Event (No body) -> Polling
    return handle_polling(table)

def create_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization"
        },
        "body": json.dumps(body)
    }