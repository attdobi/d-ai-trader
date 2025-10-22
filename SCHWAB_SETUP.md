# Schwab API Integration Setup Guide

This guide will walk you through setting up the Schwab Developer API integration for live trading with your $10,000 account.

## Prerequisites

1. **Schwab Developer Account**: Register at [developer.schwab.com](https://developer.schwab.com)
2. **Schwab Brokerage Account**: Ensure your real trading account is active
3. **thinkorswim Platform**: Must be enabled on your account (required for API trading)

## Step 1: Create Schwab Developer Application

1. Log into the Schwab Developer Portal
2. Since you've already created your application named "Trader API", you can skip to getting your credentials, or create a new application with these settings:
   - **App Name**: `Trader API` (or whatever you named your app)
   - **App Type**: `Individual`
   - **Redirect URI**: `https://localhost:8443/callback`
   - **API Products**: 
     - `Accounts and Trading Production`
     - `Market Data Production`

3. Wait for approval (can take 1-3 business days)
4. Note down your `Client ID` and `Client Secret`

## Step 2: Install Dependencies

```bash
cd /Users/adobi/d-ai-trader
pip install schwab-py>=1.6.0 requests-oauthlib>=1.3.0
```

## Step 3: Environment Configuration

1. Copy the environment template:
```bash
cp env_template.txt .env
```

2. Edit `.env` file with your credentials:
```bash
# OpenAI Configuration
OPENAI_API_KEY=your_actual_openai_key

# Schwab API Configuration  
SCHWAB_CLIENT_ID=your_schwab_client_id_here
SCHWAB_CLIENT_SECRET=your_schwab_client_secret_here
SCHWAB_REDIRECT_URI=https://localhost:8443/callback
SCHWAB_ACCOUNT_HASH=your_account_hash_here

# Trading Configuration
TRADING_MODE=simulation  # Start with simulation, change to 'live' when ready
MAX_POSITION_VALUE=2000  # Floor for per-position limit in USD
MAX_POSITION_FRACTION=0.0  # Optional: fraction of account value for per-position limit (e.g., 0.15 = 15%)
MAX_TOTAL_INVESTMENT=10000  # Floor for total invested capital
MAX_TOTAL_INVESTMENT_FRACTION=0.0  # Optional: fraction of account value for total invested capital (e.g., 0.60 = 60%)
MIN_CASH_BUFFER=500  # Minimum cash to keep in account

# Debug Configuration
DEBUG_TRADING=true
```

## Step 4: Get Your Account Hash

1. Start with `TRADING_MODE=simulation` in your .env file
2. Run the authentication process:
```bash
python3 -c "
from schwab_client import schwab_client
if schwab_client.authenticate():
    accounts = schwab_client.get_accounts()
    print('Available accounts:')
    for acc in accounts:
        print(f'  Account Hash: {acc.get(\"hashValue\", \"N/A\")}')
        print(f'  Account Number: {acc.get(\"accountNumber\", \"N/A\")}')
else:
    print('Authentication failed')
"
```

3. Copy the account hash for your trading account into the `.env` file

## Step 5: Test the Integration

1. **Test Simulation Mode First**:
```bash
# Ensure TRADING_MODE=simulation in .env
python3 -c "
from trading_interface import trading_interface
print(f'Trading mode: {trading_interface.trading_mode}')
print(f'Schwab enabled: {trading_interface.schwab_enabled}')
"
```

2. **Test Dashboard Integration**:
```bash
python3 dashboard_server.py
```
   - Open http://localhost:8080
   - Click on "Schwab Live" tab
   - Verify connection and data display

3. **Test Safety Checks**:
```bash
python3 -c "
from safety_checks import safety_manager
status = safety_manager.get_trading_status()
print('Trading Status:', status)
"
```

## Step 6: Enable Live Trading (When Ready)

⚠️ **IMPORTANT**: Only enable live trading after thorough testing!

1. **Test Thoroughly**: Ensure simulation mode works perfectly first

2. **Update Environment**:
```bash
# In .env file, change:
TRADING_MODE=live
MAX_POSITION_VALUE=2000  # Floor for per-position limit in USD
MAX_POSITION_FRACTION=0.0  # Override with your target fraction (e.g., 0.15 for 15%)
MAX_TOTAL_INVESTMENT=10000  # Floor for total invested capital
MAX_TOTAL_INVESTMENT_FRACTION=0.0  # Override with your target fraction (e.g., 0.60 for 60%)
MIN_CASH_BUFFER=500  # Keep minimum buffer
```

3. **Monitor Closely**: Watch the first few trades carefully

4. **Monitor Closely**: Watch the AI decisions and execution carefully

## Safety Features

The system includes multiple safety layers:

### Position Limits
- Maximum position value per stock
- Maximum total investment amount
- Minimum cash buffer requirement
- Position concentration limits (max 20% per stock)

### Daily Limits
- Maximum number of trades per day
- Maximum daily loss percentage (15%)

### Validation Checks
- Sufficient funds verification
- Market hours validation
- Price data availability checks
- Portfolio health monitoring

## Trading Flow

1. **News Analysis**: AI agents scrape and analyze financial news
2. **Decision Making**: AI decides on buy/sell actions
3. **Safety Validation**: All trades checked against safety limits
4. **Dual Execution**:
   - **Simulation**: Always updates dashboard database
   - **Live**: Optionally executes via Schwab API (if enabled)

## Monitoring and Alerts

### Dashboard Features
- **Main Dashboard**: Shows simulated portfolio
- **Schwab Live Tab**: Shows real account positions and P&L
- **Trade History**: All decisions and executions logged
- **Feedback System**: Performance analysis and improvements

### Manual Controls
- Manual trigger buttons for each AI agent
- Price update triggers
- Emergency stop capabilities

## Security Best Practices

1. **Environment Variables**: Never commit `.env` to version control
2. **Token Storage**: Schwab tokens stored in `schwab_tokens.json`
3. **Access Control**: API keys have limited scope and permissions
4. **Monitoring**: All trades logged with full audit trail

## Troubleshooting

### Common Issues

1. **Authentication Fails**:
   - Check client ID and secret
   - Verify redirect URI matches exactly
   - Ensure app is approved in developer portal

2. **No Account Access**:
   - Verify thinkorswim is enabled
   - Check account hash is correct
   - Confirm account is active

3. **Orders Rejected**:
   - Check market hours
   - Verify sufficient buying power
   - Review safety limit violations

4. **API Errors**:
   - Check rate limiting
   - Verify account permissions
   - Review API status and maintenance windows

### Debug Mode

Enable detailed logging:
```bash
# In .env file:
DEBUG_TRADING=true
```

Check logs:
```bash
tail -f d-ai-trader.log
```

## Testing Checklist

Before enabling live trading:

- [ ] Schwab authentication working
- [ ] Account data retrieving correctly  
- [ ] Dashboard showing live positions
- [ ] Safety checks preventing invalid trades
- [ ] Simulation trades executing properly
- [ ] All manual triggers working
- [ ] Logs showing detailed trade flow
- [ ] Error handling working correctly

## Support

For issues:
1. Check the logs in `d-ai-trader.log`
2. Verify all environment variables are set
3. Test with simulation mode first
4. Review Schwab developer documentation
5. Check system status and market hours

Remember: **Start small, monitor closely, and gradually increase exposure as you gain confidence in the system.**
