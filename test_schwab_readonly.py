#!/usr/bin/env python3
"""
SAFE READ-ONLY Schwab API Test
NO TRADES WILL BE EXECUTED - Only reads account information

This script:
1. Connects to Schwab API
2. Retrieves account balance and holdings
3. Displays the information
4. Does NOT execute any trades (read-only mode)
"""

import os
import sys
from dotenv import load_dotenv

# Setup
load_dotenv(override=True)
os.environ.setdefault("DAI_TRADER_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# CRITICAL: Set trading mode to simulation to prevent ANY real trades
os.environ["TRADING_MODE"] = "simulation"
os.environ["DAI_SCHWAB_READONLY"] = "1"  # Extra safety flag

print("="*70)
print("🔒 SCHWAB API READ-ONLY TEST")
print("="*70)
print("⚠️  SAFETY MODE: Trading disabled, read-only access only")
print("⚠️  No trades will be executed under any circumstances")
print("="*70)
print()

# Import after environment setup
try:
    from schwab_client import SchwabAPIClient
    from config import SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET, SCHWAB_ACCOUNT_HASH
    
    # Verify credentials are set
    if not SCHWAB_CLIENT_ID or SCHWAB_CLIENT_ID == "your_schwab_client_id_here":
        print("❌ ERROR: SCHWAB_CLIENT_ID not configured in .env")
        print("   Please set SCHWAB_CLIENT_ID in your .env file")
        sys.exit(1)
    
    if not SCHWAB_CLIENT_SECRET or SCHWAB_CLIENT_SECRET == "your_schwab_client_secret_here":
        print("❌ ERROR: SCHWAB_CLIENT_SECRET not configured in .env")
        print("   Please set SCHWAB_CLIENT_SECRET in your .env file")
        sys.exit(1)
    
    if not SCHWAB_ACCOUNT_HASH:
        print("❌ ERROR: SCHWAB_ACCOUNT_HASH not configured in .env")
        print("   Please set SCHWAB_ACCOUNT_HASH in your .env file")
        sys.exit(1)
    
    print("✅ Schwab credentials found in .env")
    print(f"   Client ID: {SCHWAB_CLIENT_ID[:8]}...{SCHWAB_CLIENT_ID[-4:]}")
    print(f"   Account Hash: {SCHWAB_ACCOUNT_HASH[:8]}...{SCHWAB_ACCOUNT_HASH[-4:]}")
    print()
    
    # Create client
    print("🔌 Connecting to Schwab API...")
    client = SchwabAPIClient()
    
    # Test authentication
    print("🔐 Testing authentication...")
    auth_success = client.authenticate()
    
    if not auth_success:
        print("❌ Authentication failed")
        print("   Check your credentials and try again")
        sys.exit(1)
    
    print("✅ Successfully authenticated with Schwab!")
    print()
    
    # Get account information
    print("📊 Fetching account information...")
    account_info = client.get_account_info()
    
    if not account_info:
        print("❌ Failed to retrieve account information")
        sys.exit(1)
    
    print("✅ Account information retrieved!")
    print()
    
    # Display account details
    print("="*70)
    print("💰 ACCOUNT SUMMARY")
    print("="*70)
    
    # Extract key information (structure depends on Schwab API response)
    if isinstance(account_info, dict):
        # Try to extract balance
        balance = account_info.get('cashBalance', 0)
        total_value = account_info.get('currentBalances', {}).get('liquidationValue', 0)
        
        print(f"Account Balance:    ${balance:,.2f}")
        print(f"Total Value:        ${total_value:,.2f}")
        print()
        
        # Try to extract positions
        positions = account_info.get('positions', [])
        if positions:
            print("📈 CURRENT HOLDINGS:")
            print("-" * 70)
            print(f"{'Ticker':<10} {'Shares':<12} {'Price':<15} {'Value':<15} {'P&L %':<10}")
            print("-" * 70)
            
            for pos in positions:
                ticker = pos.get('instrument', {}).get('symbol', 'Unknown')
                shares = pos.get('longQuantity', 0)
                price = pos.get('marketValue', 0) / shares if shares > 0 else 0
                value = pos.get('marketValue', 0)
                
                print(f"{ticker:<10} {shares:<12.2f} ${price:<14.2f} ${value:<14.2f}")
            
            print("-" * 70)
        else:
            print("📈 CURRENT HOLDINGS: None (all cash)")
        
        print()
        print("="*70)
        print("✅ READ-ONLY TEST COMPLETE")
        print("="*70)
        print()
        print("Next Steps:")
        print("1. Verify the account information above is correct")
        print("2. Check that holdings match your Schwab account")
        print("3. If everything looks good, you can proceed to enable live trading")
        print()
        print("⚠️  To enable live trading later:")
        print("   ./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t real_world -c 15")
        print()
        
    else:
        print(f"Account info structure: {type(account_info)}")
        print(json.dumps(account_info, indent=2)[:500])
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print()
    print("Missing dependencies for Schwab API.")
    print("Please install required packages:")
    print("   pip install schwab-api")
    print()
    
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

