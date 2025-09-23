#!/usr/bin/env python3
"""
Test Schwab API Connection
This script verifies that your Schwab credentials are properly configured
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

def test_schwab_config():
    """Test if Schwab configuration is properly set"""
    
    print("🔍 Checking Schwab API Configuration...")
    print("=" * 50)
    
    # Check each required variable
    required_vars = {
        'SCHWAB_CLIENT_ID': 'App Key',
        'SCHWAB_CLIENT_SECRET': 'Secret',
        'SCHWAB_ACCOUNT_HASH': 'Account Hash'
    }
    
    all_configured = True
    
    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        
        if value and value != f"your_{var_name.lower().replace('schwab_', '')}_here":
            # Mask the value for security (show first 4 chars only)
            masked_value = value[:4] + "*" * (len(value) - 4) if len(value) > 4 else "*" * len(value)
            print(f"✅ {var_name} ({description}): Configured [{masked_value}]")
        else:
            print(f"❌ {var_name} ({description}): Not configured or using placeholder")
            all_configured = False
    
    # Check redirect URI
    redirect_uri = os.getenv('SCHWAB_REDIRECT_URI')
    print(f"📍 Redirect URI: {redirect_uri}")
    
    # Check trading mode
    trading_mode = os.getenv('TRADING_MODE', 'simulation')
    print(f"🎮 Trading Mode: {trading_mode}")
    
    if trading_mode == 'real_world':
        print("⚠️  WARNING: Real trading mode is enabled!")
    
    print("=" * 50)
    
    if all_configured:
        print("✅ All Schwab credentials are configured!")
        print("\nNext steps:")
        print("1. Run: ./start_d_ai_trader.sh")
        print("2. The system will attempt to authenticate with Schwab")
        print("3. Check the logs for any authentication issues")
        
        # Try to import and test the client
        try:
            from schwab_client import schwab_client
            print("\n🔧 Testing Schwab client initialization...")
            
            if schwab_client:
                print("✅ Schwab client module loaded successfully")
                
                # Note: Actual authentication requires the schwab-api package
                # and may need OAuth flow
                print("\n📝 Note: Full authentication test requires:")
                print("   - schwab-api package installed")
                print("   - OAuth2 authorization flow")
                print("   - Active Schwab account")
            else:
                print("⚠️  Schwab client exists but not initialized")
                
        except ImportError as e:
            print(f"\n⚠️  Could not import Schwab client: {e}")
            print("   This is normal if schwab-api package is not installed yet")
            
    else:
        print("❌ Some credentials are missing!")
        print("\nPlease edit your .env file and add:")
        print("1. Your Schwab App Key (from developer portal)")
        print("2. Your Schwab Secret (from developer portal)")  
        print("3. Your Account Hash (from your Schwab account)")
        print("\nDO NOT share these credentials with anyone!")
    
    # Check OpenAI key too
    print("\n🤖 Checking OpenAI Configuration...")
    openai_key = os.getenv('OPENAI_API_KEY')
    if openai_key and openai_key != 'your_openai_api_key_here':
        masked_key = openai_key[:8] + "*" * (len(openai_key) - 12) + openai_key[-4:] if len(openai_key) > 12 else "*" * len(openai_key)
        print(f"✅ OPENAI_API_KEY: Configured [{masked_key}]")
    else:
        print("❌ OPENAI_API_KEY: Not configured or using placeholder")

if __name__ == "__main__":
    test_schwab_config()
