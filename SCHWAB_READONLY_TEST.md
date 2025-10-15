# Schwab API Read-Only Test

## ⚠️ IMPORTANT - Safety First!

Before connecting to live Schwab API, we need to verify the connection works correctly **WITHOUT executing any trades**.

## Step 1: Configure Schwab Credentials

Edit your `.env` file and add:

```bash
# Schwab API Credentials
SCHWAB_CLIENT_ID=your_client_id_here
SCHWAB_CLIENT_SECRET=your_client_secret_here
SCHWAB_REDIRECT_URI=https://localhost:8443/callback
SCHWAB_ACCOUNT_HASH=your_account_hash_here
```

**How to get these:**
1. Go to https://developer.schwab.com/
2. Create an application
3. Copy the Client ID and Client Secret
4. Set redirect URI to `https://localhost:8443/callback`
5. Get your account hash from Schwab

## Step 2: Install Schwab API Package

```bash
cd /Users/adobi/d-ai-trader
source dai/bin/activate
pip install schwab-api
```

## Step 3: Run Read-Only Test

```bash
python test_schwab_readonly.py
```

**This script will:**
- ✅ Connect to Schwab API
- ✅ Authenticate with your credentials
- ✅ Retrieve account balance
- ✅ Retrieve current holdings
- ✅ Display everything
- ⛔ **NOT execute ANY trades** (read-only mode)

## Step 4: Verify Results

Check that the displayed information matches your actual Schwab account:
- Account balance
- Stock holdings
- Position values

## Step 5: Enable Live Trading (ONLY after verification)

Once you've verified the read-only test works correctly:

```bash
# Start with live trading enabled (15-minute aggressive day trading)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t real_world -c 15
```

**Safety Features:**
- Market hours protection (no trades after 1 PM PT)
- Position size limits ($1500-$4000)
- Max total investment limits
- Safety checks on every trade
- Simulation mode runs in parallel for comparison

## Emergency Stop

If you need to stop the system:
```bash
pkill -f d_ai_trader.py
pkill -f dashboard_server.py
```

## Monitoring

Monitor live trades on the dashboard:
- **Dashboard tab**: Shows portfolio value in real-time
- **Trades tab**: Shows all decisions and executions
- **Schwab tab**: Shows live Schwab account data
- **Feedback tab**: Shows AI performance and learning

## Safety Checklist

Before going live, verify:
- [ ] Read-only test completed successfully
- [ ] Account balance matches Schwab
- [ ] Holdings match Schwab
- [ ] You understand the aggressive day trading strategy
- [ ] You're comfortable with 5-10% profit targets and -3% to -5% stop losses
- [ ] You've reviewed recent simulation results
- [ ] You have monitored at least one full day in simulation mode

