import requests
import configparser
import os
import json
from pprint import pprint

# --- Configuration ---
SETTINGS_FILE = 'settings.ini'
API_URL = "https://redacted.sh/ajax.php?action=top10"

def main():
    """
    Makes a test request to the REDacted API to verify connectivity and authentication.
    """
    print("--- REDacted API Test ---")

    # 1. Read API Key from settings.ini
    if not os.path.exists(SETTINGS_FILE):
        print(f"Error: {SETTINGS_FILE} not found. Please run this script in the same directory.")
        return

    config = configparser.ConfigParser()
    config.read(SETTINGS_FILE)
    
    try:
        api_key = config['DEFAULT']['RED_API']
        if not api_key:
            raise KeyError
    except KeyError:
        print(f"Error: 'RED_API' key not found or is empty in {SETTINGS_FILE}.")
        return

    print("Successfully read API key from settings.ini.")

    # 2. Prepare and send the request
    headers = {
        "Authorization": api_key,  # <-- CORRECTED: Removed the "token " prefix for REDacted
        # "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    }
    params = {
        "type": "torrents"
    }

    print(f"Sending request to: {API_URL}")

    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=20)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        # 3. Process the response
        print(f"Request successful with status code: {response.status_code}")
        
        # Try to parse the response as JSON
        response_json = response.json()
        
        print("\n--- API Response (Success) ---")
        if response_json.get('status') == 'success':
            print("API status is 'success'. Parsing top 10 categories...")
            categories = response_json.get('response', [])
            for category in categories:
                print(f"- Found category: {category.get('caption')}")
        else:
            print("API status is 'failure'. Full response:")
            pprint(response_json)

    except requests.exceptions.HTTPError as http_err:
        print(f"\n--- API Response (HTTP Error) ---")
        print(f"HTTP Error occurred: {http_err}")
        print(f"Status Code: {response.status_code}")
        print("Response Text:")
        print(response.text)
    except requests.exceptions.RequestException as req_err:
        print(f"\n--- API Response (Request Error) ---")
        print(f"An error occurred during the request: {req_err}")
    except json.JSONDecodeError:
        print("\n--- API Response (JSON Decode Error) ---")
        print("The server did not return a valid JSON response.")
        print("This usually means a security challenge page (like Cloudflare) was returned instead of API data.")
        print("Response Text:")
        print(response.text)


if __name__ == "__main__":
    main()
