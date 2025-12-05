# 🤖 D-AI-Trader - AI-Powered Day Trading System

An autonomous **swing/short-term trading system** powered by **GPT-5.1 (default reasoning)** with GPT-4o/4.1 Vision for screenshots. It analyzes financial news screenshots, makes selective trading decisions, and executes trades roughly every **3 hours** during market hours. Default behavior targets **1–3 day holding periods** for cash accounts that must wait for **settled funds (T+1)**; enable margin mode only if you have $25k+ and want to reuse proceeds immediately.

---

## 🚀 Quick Start

### **Simulation Mode (Safe Testing)**
```bash
# Default pacing – every 3 hours (aligns with settled-funds workflow, GPT-5.1 default)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t simulation -c 180

# Faster loops for experimentation (15 or 60 minutes)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t simulation -c 60
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t simulation -c 15
```

> **Account type toggle:** `IS_MARGIN_ACCOUNT=0` (default) keeps buys limited to settled funds and a 1–3 day rhythm. Set `IS_MARGIN_ACCOUNT=1` only if you have a $25k+ margin account and want to reuse proceeds immediately (PDT rules apply).
>
> **Prompt profile toggle:** add `-P gpt-pro` (or set `DAI_PROMPT_PROFILE=gpt-pro`) to run the Decider with the GPT-Pro optimized profit-taking prompt; leave it as `standard` for the default profile.

### **Schwab API Read-Only Test (Before Going Live)**
```bash
# View real holdings & balances without trades
./start_schwab_live_view.sh -p 8080

# Then open: http://localhost:8080/schwab
```

### **Live Trading Pilot (One Buy Decision)**
```bash
# Launch live trading in read-only mode first, then:

# Single-buy pilot – will execute at most ONE buy order per cycle
./start_live_trading.sh --port 8080 --model gpt-5.1 --cadence 180

# Environment overrides (optional):
#   export DAI_MAX_TRADES=1      # already set by start_live_trading.sh
#   export DAI_SCHWAB_INTERACTIVE=0  # skip ENTER prompt
```

> **Auth refresh reminder**: Schwab refresh tokens expire roughly every 7 days. If you see
> `refresh_token_authentication_error`, delete `schwab_tokens.json`, run `./test_schwab_api.sh`
> to complete the OAuth flow again, and restart your live view/streaming scripts. During the
> OAuth approval, make sure the `trade` scope is selected in the Schwab developer portal so the
> API returns live balances and allows order placement.

### **Manual OAuth Helper (Alternative Token Bootstrap)**
```bash
# Launch browser for the 3-legged OAuth flow and save tokens
SCHWAB_CLIENT_ID=... SCHWAB_CLIENT_SECRET=... ./schwab_manual_auth.py --save

# Refresh an existing token file before it expires (uses refresh_token)
SCHWAB_CLIENT_ID=... SCHWAB_CLIENT_SECRET=... ./schwab_manual_auth.py --refresh --save
```

### **Quick schwab-py Bootstrap (auto-refreshing helper)**
```python
from schwab.auth import easy_client

c = easy_client(
    api_key="YOUR_APP_KEY",
    app_secret="YOUR_APP_SECRET",
    callback_url="https://127.0.0.1:5556/callback",  # must match portal entry
    token_path="./schwab_tokens.json",
)

acct_map = c.get_account_numbers().json()
print(acct_map[:1])
```

### **Intraday Streaming Helper (Live Quotes + Account Activity)**
```bash
# Streams Level-One equities quotes and refreshes holdings on fills
./run_schwab_streaming.py            # auto-detect symbols from current positions

# OR target a custom watchlist
DAI_STREAM_SYMBOLS="SPY,AAPL,QQQ" ./run_schwab_streaming.py
```
> The streaming helper keeps a shadow ledger (unsettled cash, open-order reserves) so
> “Funds Available (effective)” updates immediately after fills even when the Schwab
> snapshot lags. Both `start_schwab_live_view.sh` and `start_live_trading.sh` launch it by
> default; add `--no-stream` to disable.

### **Probe Live Funds vs Ledger**
```bash
python effective_funds_probe.py
# {
#   "baseline_funds": 1234.56,
#   "effective_funds": 3456.78,
#   "ledger_components": { ... }
# }
```

### **Full Live Trading (Automation Enabled)**
```bash
# After verifying the pilot, remove the trade cap and increase cadence as desired
export DAI_MAX_TRADES=5          # or your preferred limit
export DAI_SCHWAB_READONLY=0     # ensure live orders are allowed
export DAI_SCHWAB_LIVE_VIEW=0    # full automation mode

# Cash default: keep 180–60 min cadence for settled-funds compliance; use 15 min only if IS_MARGIN_ACCOUNT=1 (PDT $25k+)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -t real_world -c 15
```

**Dashboard:** http://localhost:8080

---

## 🎯 Day Trading Strategy

### **Trading Philosophy**
- ⚡ **Quick Profits**: Target 5-10% gains per trade, exit fast
- 🔄 **Selective Entries**: ~2–3 high-conviction trades/day (3-hour cadence)
- 📈 **Momentum Trading**: Ride trends, exit before reversals
- 💰 **Capital Rotation**: Sell winners, redeploy into new opportunities
- 🛡️ **Risk Management**: Fast stop losses, position limits

### **Profit Targets**
- ✅ **5-8% gain** → SELL (lock it in!)
- ✅ **8-15% gain** → SELL (great trade!)
- ✅ **15%+ gain** → SELL NOW (exceptional!)
- ⚠️ **-3% to -5% loss** → SELL (stop loss, protect capital)

### **Position Sizing**
- Minimum: $1500 per trade
- Optimal: $2000-$3500
- Maximum: $4000 per trade
- Max positions: 5 stocks at once

---

## ⏰ Daily Trading Schedule

### **Opening Bell Sequence**
```
6:30 AM PT (9:30 AM ET) - Summarizer + Decider run at the opening bell (executes trades 10 seconds after summarize step)
```

### **Intraday Trading**
```
6:30 AM, 9:30 AM, 12:30 PM PT - Repeat cycles every ~3 hours (default 180‑min cadence)
   ├─ Scan 6 news sources
   ├─ Re-evaluate positions (1–3 day thesis)
   ├─ Make selective trading decisions (respect pacing/cooldown)
   └─ Execute trades (during market hours only)
```

### **End of Day**
```
1:00 PM PT (4:00 PM ET) - Market closes
1:30 PM PT (4:30 PM ET) - Daily performance feedback & analysis
```

### **After Hours**
```
Decisions recorded but marked "⛔ MARKET CLOSED"
No trades executed - portfolio unchanged
```

---

## 🛡️ Financial Guardrails

### **AI Hallucination Prevention**
- ❌ Cannot sell stocks you don't own
- ❌ Cannot buy stocks you already own (must sell first)
- ❌ Cannot ignore current holdings
- ✅ Validates every decision before execution

### **Trading Limits**
- Position size: $1500-$4000
- Max positions: 5 stocks
- Cash buffer: Always maintained
- Market hours: Only 6:30 AM - 1:00 PM PT (M-F)

### **Good-Faith & Margin Compliance**
- **Cash accounts (default)**: Set `IS_MARGIN_ACCOUNT=0` (or leave unset). Buys use **settled funds only**, so sell proceeds settle **T+1**. The 3-hour cadence and **1–3 day holding period** keep the strategy compliant with good-faith rules.
- **Margin accounts**: Set `IS_MARGIN_ACCOUNT=1` **only if you have a $25k+ margin account** and want to reuse same-day proceeds (“funds available for trading”) right after a sell. Pattern-day-trader and maintenance rules still apply—confirm with your broker.
- **High-frequency intraday trading** (15–30 minute cadence) is only recommended with margin accounts that meet PDT requirements.

### **Multi-Layer Safety (Real Trading)**
1. `DAI_SCHWAB_READONLY` flag check
2. `TRADING_MODE` must be "real_world"
3. Market must be open
4. Decision validator approval
5. Safety manager checks

---

## 📰 News Sources (6 Total)

| Source | Focus | Reliability |
|--------|-------|-------------|
| **Yahoo Finance** | Stock news, earnings | ✅ Very reliable |
| **Benzinga** ⭐ | Day trading catalysts, movers | ✅ Best for day trading |
| **Fox Business** | Market sentiment | ✅ Reliable |
| **AP Business** | Clean, factual news | ✅ Simple, trusted |
| **BBC Business** | International markets | ✅ No US bot detection |
| **CNBC** | Breaking news, market movers | ✅ Great content |

**All sources work with headless Chrome automation (no bot detection).**

---

## 🤖 AI Models

### **Recommended for Trading**
- **gpt-5.1** ⭐ - Default reasoning model (strongest decisions)
  - Uses ~8000 completion tokens for richer reasoning
  - Decider auto-falls back to gpt-4.1 if GPT-5.1 returns empty JSON
  - Best quality; higher cost than 4o/4.1

- **gpt-4o** - Cost-efficient alt ($2.50/$10 per 1M tokens)
  - Reliable JSON parsing + vision
  - Use `--model gpt-4o` to cut spend if GPT-5.1 cost is a concern

- **gpt-4.1** - Fully supported fallback (same API schema as gpt-4o)
  - Good math/tooling improvements
  - Pairs well with 2800 token cap for multi-buy outputs

- **gpt-4o-mini** - Cheap testing ($0.15/$0.60 per 1M tokens)
  - Faster, lower quality; simulation only

### **Experimental**
- **gpt-5** / **gpt-5-mini** - Earlier reasoning variants (⚠️ token-hungry)
  - No custom temperature
  - Use only for experimentation

### **NOT Supported**
- ❌ o1/o3 models - Don't support system messages or JSON mode

---

## 💻 Installation

### **Prerequisites**
- Python 3.9+
- PostgreSQL database
- Chrome browser (v141+)
- OpenAI API key
- (Optional) Schwab API credentials for live trading

### **Setup**
```bash
# 1. Clone repository
git clone <your-repo>
cd d-ai-trader

# 2. Configure environment
cp env_template.txt .env
# Edit .env with your API keys

# 3. Start the system (auto-creates venv & installs dependencies)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15
```

### **Required in `.env`**
```bash
# OpenAI API (Required)
OPENAI_API_KEY=sk-proj-your_actual_api_key_here

# Account type (Required decision)
# 0 = cash account (default; buys only with settled funds, 1–3 day cadence)
# 1 = margin account ($25k+ only; reuses same-day proceeds, PDT rules apply)
IS_MARGIN_ACCOUNT=0

# Schwab API (Optional - for live trading)
SCHWAB_CLIENT_ID=your_client_id
SCHWAB_CLIENT_SECRET=your_client_secret
SCHWAB_ACCOUNT_HASH=your_account_hash
SCHWAB_REDIRECT_URI=https://127.0.0.1:5556/callback

# Prompt & logging overrides (Optional)
# DAI_PROMPT_PROFILE=standard   # set to gpt-pro to use the GPT-Pro optimized Decider prompt
# DAI_DECIDER_RAW_PREVIEW=4000  # number of characters from the raw Decider completion to print for debugging
```

---

## 🎮 Usage

### **Command Line Options**
```bash
./start_d_ai_trader.sh [OPTIONS]

Options:
  -p, --port PORT           Dashboard port (default: 8080)
  -m, --model MODEL         AI model (default: gpt-5.1)
  -v, --prompt-version VER  auto | vN (default: auto)
  -P, --prompt-profile OPT  standard | gpt-pro (default: standard)
  -t, --trading-mode MODE   simulation | real_world (default: simulation)
  -c, --cadence MINUTES     180 (default) | 60 | 30 | 15
```

### **Examples**
```bash
# Default swing cadence (~3 hours)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t simulation -c 180

# Cost saver (hourly loop)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 60

# Compare two models (hourly loop)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t simulation -c 60
./start_d_ai_trader.sh -p 8081 -m gpt-4o -v auto -t simulation -c 60

# Live trading (settled-funds cadence)
./start_d_ai_trader.sh -p 8080 -m gpt-5.1 -v auto -t real_world -c 180
```

---

## 📊 Dashboard Tabs

### **1. Dashboard** (Main)
- Portfolio value, cash balance, P&L
- Current holdings with gain/loss
- Interactive charts (portfolio history, performance)
- Enhanced Schwab card (shows settled vs raw cash, funds-available components, margin indicator)
- Manual trigger buttons (Run All Agents, etc.)

### **2. Trades**
- All trading decisions with timestamps
- Ticker, Action, Shares, Amount, Reason (tickers link to Yahoo Finance and include a quick “Chart” popup button)
- Config-specific filtering
- Shows "MARKET CLOSED" flag for after-hours decisions

### **3. Summaries**
- Latest news analysis from all 6 sources
- Headlines and insights extracted by AI
- Timestamped in Pacific Time

### **4. Feedback**
- Win rate, average profit metrics
- Trade outcomes table (completed sells)
- Performance analysis
- AI learning insights

### **5. Schwab** (Live Trading)
- Real Schwab account balance
- Live holdings and positions
- Day trading power, buying power
- Real-time sync with broker

---

## 🔒 Safety Features

### **Before Live Trading**
1. ✅ Complete read-only Schwab test (`./test_schwab_api.sh`)
2. ✅ Run simulation for 1+ full trading days
3. ✅ Review all trades and verify strategy
4. ✅ Read `GO_LIVE_CHECKLIST.md` completely
5. ✅ Understand risk: day trading is volatile!

### **During Live Trading**
- Market hours enforcement (no after-hours execution)
- Position size limits ($1500-$4000)
- Decision validation (prevents hallucinations)
- Stop losses (-3% to -5%)
- Real-time monitoring required

### **Emergency Stop**
```bash
pkill -f d_ai_trader.py
pkill -f dashboard_server.py
```

---

## 📈 Expected Performance

### **Legacy 15-Minute Cadence (optional)**
- Trading opportunities: ~27 per day
- Target per trade: 5-10% gain
- Win rate: 50-60%
- Daily gain potential: 15-25%
- Monthly gain potential: 300-500%+

> ⚠️ This high-frequency mode is only recommended with margin accounts and larger balances. It also pushes API usage to ~$10/day because of the 26 intraday cycles.

---

## 🛠️ Key Files

```
├── d_ai_trader.py              # Main orchestrator with scheduling
├── main.py                     # News scraping & screenshot analysis
├── decider_agent.py            # Trading decision engine
├── decision_validator.py       # Financial guardrails (prevents hallucinations)
├── feedback_agent.py           # Performance analysis
├── dashboard_server.py         # Web interface & API
├── config.py                   # AI model configuration
├── schwab_client.py            # Schwab API integration
├── trading_interface.py        # Unified trading layer
├── start_d_ai_trader.sh        # Main startup script
├── test_schwab_api.sh          # Safe Schwab API testing
├── GO_LIVE_CHECKLIST.md        # Pre-flight safety checklist
└── SCHWAB_READONLY_TEST.md     # Schwab testing guide
```

---

## 🔧 Configuration

### **Trading Modes**
- `simulation` - Test strategies safely (default)
- `real_world` - Execute real trades via Schwab API

### **Cadence Options**
- `15` - Aggressive (27 opportunities/day)
- `30` - Active (14 opportunities/day)
- `60` - Conservative (7 opportunities/day)

### **Prompt Versions**
- `auto` - Uses latest prompt version (learns from feedback)
- `v4` - Fixed baseline prompt (for controlled testing)

---

## 📚 Documentation

- `GO_LIVE_CHECKLIST.md` - Complete safety guide for live trading
- `SCHWAB_READONLY_TEST.md` - How to test Schwab API safely
- `SCHWAB_API_SETUP.md` - Schwab API configuration guide
- `FEEDBACK_SYSTEM.md` - How the AI learning system works
- `AUTOMATION_README.md` - Scheduling and automation details

---

## 🎓 How It Works

### **Every Trading Cycle (15-60 minutes)**

1. **News Collection** (Summarizer Agents)
   - Screenshot 6 financial news sites
   - GPT-4o Vision analyzes screenshots
   - Extracts headlines and trading insights

2. **Decision Making** (Decider Agent)
   - Reviews current portfolio (holdings, P&L)
   - Analyzes news summaries
   - Makes trading decisions:
     - SELL positions with profits (5-10%) or losses (-3% to -5%)
     - HOLD positions with continuing momentum
     - BUY new opportunities with strong catalysts

3. **Validation** (Financial Guardrails)
   - Prevents hallucinations (can't sell stocks you don't own)
   - Enforces position limits
   - Validates amounts and tickers

4. **Execution** (Only During Market Hours)
   - Updates portfolio in simulation mode
   - Executes real trades via Schwab API (if enabled)
   - Records all decisions and outcomes

5. **Feedback** (Daily at Market Close)
   - Analyzes completed trades
   - Calculates win rate and average profit
   - Stores lessons learned (high-level only)

---

## 💰 Cost Analysis

### **API Costs (GPT-4o, default cadence)**
- 6 sources × 3 cycles/day ≈ 18 calls/day
- ~5K tokens per screenshot analysis
- ~90K tokens/day total (~0.09M)
- **Input**: ~$0.25/day
- **Output**: ~$0.75/day (decider + helpers)
- **Total**: ~$1/day or ~$30/month (lower if you pause cycles)

### **Potential Returns**
- 2–3 high-conviction trades/day × 3–5% targets with disciplined stops
- With $10K cash account = steady compounding while avoiding good-faith violations
- Faster cadences (15/30 min) remain available for margin users who accept higher risk
- **API costs (~$1/day) are negligible vs. trading profits**

---

## ⚠️ Risks & Disclaimers

- **Day trading is risky** - You can lose money
- **Past performance doesn't guarantee future results**
- **This is experimental AI** - Monitor closely, especially initially
- **Start in simulation mode** - Test thoroughly before live trading
- **Use money you can afford to lose**
- **This is not financial advice** - Use at your own risk

---

## 🔧 Advanced Features

### **Parallel Configurations**
Run multiple strategies simultaneously:
```bash
# Terminal 1: GPT-4o with 15-min cadence
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15

# Terminal 2: GPT-5 with 30-min cadence (comparison)
./start_d_ai_trader.sh -p 8081 -m gpt-5-mini -v auto -t simulation -c 30
```

Each gets a unique `config_hash` - completely isolated data!

### **Manual Testing**
Dashboard has manual trigger buttons:
- 📰 Run Summarizer Agents (collect news now)
- 🤖 Run Decider Agent (make decisions now)
- 📊 Run Feedback Agent (analyze performance now)
- 🚀 Run All Agents (full cycle now)

---

## 🐛 Troubleshooting

### **ChromeDriver Issues**
```bash
# The system auto-detects Chrome v141 and downloads matching driver
# If you see version mismatch, restart the system
```

### **API Key Errors**
```bash
# Edit .env and add your real OpenAI API key
OPENAI_API_KEY=sk-proj-YOUR_ACTUAL_KEY_HERE
```

### **Market Closed**
```bash
# Trades show "⛔ MARKET CLOSED - No action taken"
# This is normal outside 9:30 AM - 4:00 PM ET (Mon-Fri)
# Decisions are recorded but not executed
```

### **Emergency Stop**
```bash
pkill -f d_ai_trader.py
pkill -f dashboard_server.py
```

---

## 📞 Support

- Read `GO_LIVE_CHECKLIST.md` before enabling real trading
- Check `SCHWAB_READONLY_TEST.md` for safe API testing
- Review logs in `d-ai-trader.log`

---

## 📜 License

Use at your own risk. This is experimental software for educational purposes.

---

## 🎉 Recent Updates

### **December 2025 - Prompt + UI Enhancements**
- ✅ New `-P/--prompt-profile` flag (and `DAI_PROMPT_PROFILE`) to switch between the classic and GPT-Pro optimized Decider prompts at launch.
- ✅ Trades tab tickers now link to Yahoo Finance and include a quick “Chart” popup button for rapid inspection.
- ✅ Schwab dashboard card now differentiates settled funds, raw cash, and margin status to keep T+1 guardrails obvious.
- ✅ Added `DAI_DECIDER_RAW_PREVIEW` env var to dump raw Decider JSON for debugging without editing code.
- ✅ Scheduler auto-runs a market-open catch-up if the orchestrator starts after 6:30 AM PT, and manual trigger buttons now coordinate properly with scheduled cycles.

### **October 2025 - Major Overhaul**
- ✅ GPT-4o Vision for screenshot analysis
- ✅ GPT-5 support (reasoning models)
- ✅ Configurable trading cadence (15/30/60 min)
- ✅ Opening bell strategy (9:30:05 AM execution)
- ✅ Financial guardrails (prevents AI hallucinations)
- ✅ Shares column on Trades tab
- ✅ Market hours protection (4 layers)
- ✅ Schwab read-only testing mode
- ✅ 6 reliable news sources (no bot detection)
- ✅ Aggressive day trading prompts
- ✅ Pacific Time display (PDT/PST)
- ✅ Config isolation for parallel runs
- ✅ Feedback system simplified (no auto-rewrite)
- ❌ Removed GPT-4.1 support
- ❌ Removed auto-prompt generation (too aggressive)

---

**Happy Trading! 📈🚀**
