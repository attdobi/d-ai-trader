#!/usr/bin/env python3
"""
Get Schwab Account Hash
This script helps you retrieve your account hash after initial authentication
"""

import os
import webbrowser
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

def get_auth_url():
    """Generate the Schwab authorization URL"""
    client_id = os.getenv('SCHWAB_CLIENT_ID')
    redirect_uri = os.getenv('SCHWAB_REDIRECT_URI', 'https://127.0.0.1:5556')
    
    if not client_id or client_id == 'your_schwab_client_id_here':
        print("❌ Please set your SCHWAB_CLIENT_ID (App Key) in .env file first!")
        return None
    
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}"
    
    return auth_url

def main():
    print("🔐 Schwab Account Hash Retrieval Helper")
    print("=" * 50)
    
    auth_url = get_auth_url()
    
    if auth_url:
        print("\n📋 Step 1: Authorize your app")
        print(f"Visit this URL in your browser:\n")
        print(auth_url)
        print("\n(Opening in your default browser...)")
        
        webbrowser.open(auth_url)
        
        print("\n📋 Step 2: After logging in and authorizing:")
        print("1. You'll be redirected to a URL like:")
        print("   https://127.0.0.1:5556?code=AUTH_CODE_HERE&...")
        print("2. Copy the AUTH_CODE from the URL")
        print("3. Use this code to get your access token")
        
        print("\n📋 Step 3: Getting your account hash")
        print("Once authenticated, the API will return your account details")
        print("including the account hash/number you need.")
        
        print("\n⚠️  Note: You may need to:")
        print("1. Install the schwab-py package: pip install schwab-py")
        print("2. Handle the OAuth2 flow to exchange the code for tokens")
        print("3. Make an API call to get account numbers")
        
        print("\n📚 Alternatively, your account hash might simply be:")
        print("- Your 8-digit Schwab account number (e.g., 12345678)")
        print("- Check your Schwab account page at schwab.com")

if __name__ == "__main__":
    main()
