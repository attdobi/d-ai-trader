# 🚀 Go Live Checklist - D-AI-Trader

## ⚠️ CRITICAL: Complete ALL steps before enabling live trading

### Phase 1: Schwab API Read-Only Test ✓

**Goal:** Verify Schwab API connection works WITHOUT executing any trades.

#### Step 1.1: Configure Schwab Credentials

Edit `.env` file:
```bash
SCHWAB_CLIENT_ID=your_client_id_from_schwab_developer
SCHWAB_CLIENT_SECRET=your_client_secret_from_schwab_developer
SCHWAB_REDIRECT_URI=https://localhost:8443/callback
SCHWAB_ACCOUNT_HASH=your_encrypted_account_number
```

Get these from: https://developer.schwab.com/

#### Step 1.2: Run Read-Only Test

```bash
./test_schwab_api.sh
```

**This script:**
- ✅ Connects to Schwab API (read-only)
- ✅ Shows account balance and holdings
- ⛔ **NO trades executed** (safety locked)
- ⛔ No automation running (dashboard only)

#### Step 1.3: Verify Data

Open: http://localhost:8080/schwab

Check:
- [ ] Account balance matches your Schwab account
- [ ] Holdings match (ticker, shares, prices)
- [ ] You see "🔒 READ-ONLY MODE" banner
- [ ] No errors in console

**DO NOT PROCEED until all checks pass!**

---

### Phase 2: Simulation Testing ✓

**Goal:** Run full system in simulation mode for at least 1 trading day.

#### Step 2.1: Run Full Simulation

```bash
# Conservative (every hour)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 60

# OR Aggressive (every 15 min)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15
```

#### Step 2.2: Monitor Full Trading Day

Watch for:
- [ ] Opening bell trade (6:30:05 AM PT)
- [ ] Regular cadence trades execute on schedule
- [ ] Profit taking at 5-10% gains
- [ ] Stop losses at -3% to -5%
- [ ] No trades after 1:00 PM PT (market close)
- [ ] Feedback analysis at 1:30 PM PT

#### Step 2.3: Review Performance

Check dashboard:
- [ ] Portfolio value makes sense
- [ ] Trades logged correctly
- [ ] No system errors
- [ ] Market hours protection works
- [ ] Config isolation works

---

### Phase 3: Go Live (ONLY after Phase 1 & 2 complete) ✓

**Goal:** Enable live trading with Schwab API.

#### Step 3.1: Final Safety Verification

- [ ] Completed read-only Schwab test successfully
- [ ] Completed at least 1 full day of simulation
- [ ] Reviewed and understood all trades
- [ ] Comfortable with aggressive day trading strategy
- [ ] Have emergency stop plan ready
- [ ] Know how to kill the process (`pkill -f d_ai_trader.py`)

#### Step 3.2: Enable Live Trading

**Start with conservative cadence first:**
```bash
# Conservative start - every hour
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t real_world -c 60
```

**After confirming it works, can increase to aggressive:**
```bash
# Aggressive day trading - every 15 minutes
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t real_world -c 15
```

#### Step 3.3: Monitor First Live Trades

**WATCH CLOSELY:**
- [ ] First trade executes correctly
- [ ] Schwab API confirms execution
- [ ] Account balance updates
- [ ] Holdings sync with Schwab
- [ ] Stop losses trigger correctly
- [ ] Profit targets hit correctly

---

## 🚨 Emergency Procedures

### Stop All Trading Immediately
```bash
pkill -f d_ai_trader.py
pkill -f dashboard_server.py
```

### Return to Simulation Mode
```bash
# Just restart in simulation mode
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15
```

### Check What's Running
```bash
ps aux | grep -E "d_ai_trader|dashboard_server"
```

---

## 📊 Trading Strategy Summary

**Day Trading Parameters:**
- **Profit Targets:** 5-8% (quick), 8-15% (great), 15%+ (exceptional)
- **Stop Losses:** -3% to -5% (protect capital)
- **Position Size:** $1500-$4000 per trade
- **Max Positions:** 5 stocks at once
- **Cadence:** 15-60 minutes

**Market Hours:**
- **Opens:** 6:30 AM PT (9:30 AM ET)
- **Closes:** 1:00 PM PT (4:00 PM ET)
- **Days:** Monday-Friday only

**Daily Schedule:**
- 6:25 AM PT - Pre-market analysis
- 6:30:05 AM PT - Opening bell trade
- 6:35 AM - 1:00 PM - Intraday cycles (every N min)
- 1:30 PM PT - Daily feedback

---

## 💰 Expected Results

**With 15-minute cadence:**
- Up to 27 trading opportunities per day
- Target 5-10% per trade
- ~50% win rate expected
- Daily portfolio gain: 15-25% potential

**Risk Management:**
- Fast stop losses (-3% to -5%)
- Position limits ($4000 max)
- Cash buffer maintained
- Market hours protection

---

## ✅ Pre-Flight Checklist

Before going live, confirm:
- [ ] Read `.env` has real Schwab credentials
- [ ] Read-only test passed (Phase 1)
- [ ] Simulation test passed (Phase 2)
- [ ] You understand the strategy
- [ ] You know how to emergency stop
- [ ] You're monitoring the first day closely
- [ ] You've set appropriate position size limits

**Only proceed when ALL boxes are checked!** ✅

