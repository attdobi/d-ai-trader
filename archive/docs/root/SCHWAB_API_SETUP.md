# Schwab API Setup Guide

## Prerequisites
1. Schwab Developer Account
2. Schwab Brokerage Account
3. App Key and Secret from Schwab Developer Dashboard

## Step 1: Get Your Schwab API Credentials

1. Go to https://developer.schwab.com/
2. Sign up for a developer account if you don't have one
3. Create a new app in the dashboard
4. Note down your:
   - **App Key** (this is your SCHWAB_CLIENT_ID)
   - **Secret** (this is your SCHWAB_CLIENT_SECRET)
   - **Account Hash** (from your brokerage account)

## Step 2: Configure Environment Variables

Create a `.env` file in the project root (if it doesn't exist):

```bash
cp env_template.txt .env
```

Edit the `.env` file and add your Schwab credentials:

```env
# Schwab API Configuration
SCHWAB_CLIENT_ID=your_app_key_here
SCHWAB_CLIENT_SECRET=your_secret_here
SCHWAB_REDIRECT_URI=https://localhost:8443/callback
SCHWAB_ACCOUNT_HASH=your_account_hash_here

# Trading Mode - IMPORTANT!
# Use 'simulation' for testing, 'real_world' for live trading
TRADING_MODE=simulation
```

## Step 3: Install Schwab Python Package

The project needs the Schwab API Python package. Install it:

```bash
pip install schwab-api
```

Or if using the charles-schwab-api package:

```bash
pip install charles-schwab-api
```

## Step 4: Test Your Configuration

Run the test script to verify your Schwab setup:

```python
python test_schwab_connection.py
```

## Step 5: Enable Real Trading (CAUTION!)

To enable real trading through Schwab:

1. Change `TRADING_MODE` in your `.env` file:
   ```env
   TRADING_MODE=real_world
   ```

2. Start the system with real trading mode:
   ```bash
   ./start_d_ai_trader.sh -t real_world
   ```

⚠️ **WARNING**: Real trading mode will execute actual trades with real money!

## Using Schwab API for Stock Prices

The system currently uses Yahoo Finance for stock prices, but you can use Schwab's API instead:

### Advantages of Schwab API for Prices:
- Real-time quotes during market hours
- More reliable than Yahoo Finance
- No rate limiting issues
- Direct from your broker

### Disadvantages:
- Only works when authenticated
- Requires active Schwab account
- May have different symbols for some securities

### To Enable Schwab Price Quotes:

The system would need modifications in `decider_agent.py`:

```python
def get_current_price(ticker):
    # Try Schwab first if available
    if schwab_client.is_authenticated:
        price = schwab_client.get_quote(ticker)
        if price:
            return price
    
    # Fallback to Yahoo Finance
    return get_current_price_yahoo(ticker)
```

## Security Notes

1. **Never commit your `.env` file** - it's in `.gitignore` for safety
2. **Use simulation mode** until you're confident in the system
3. **Set position limits** in the environment variables
4. **Monitor your account** regularly when using real trading

## Troubleshooting

### Authentication Issues
- Ensure your App Key and Secret are correct
- Check that your redirect URI matches exactly
- Verify your account hash is correct

### Connection Issues
- The Schwab API requires OAuth2 authentication
- You may need to manually authorize the app first
- Check firewall settings for port 8443

### Trading Issues
- Ensure you have sufficient funds
- Check market hours (9:30 AM - 4:00 PM ET)
- Verify your account has trading permissions

## Support

For Schwab API issues:
- Documentation: https://developer.schwab.com/docs
- Support: Contact Schwab Developer Support

For D-AI-Trader issues:
- Check the logs in `d-ai-trader.log`
- Review error messages in the dashboard
- Ensure all dependencies are installed
