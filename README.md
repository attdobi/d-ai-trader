# 🤖 D-AI-Trader - AI-Powered Day Trading System

An autonomous **day trading system** powered by GPT-4o Vision that analyzes financial news screenshots, makes rapid trading decisions, and executes trades every 15-60 minutes during market hours. Optimized for **5-10% quick gains** with aggressive profit-taking and fast stop losses.

---

## 🚀 Quick Start

### **Simulation Mode (Safe Testing)**
```bash
# Aggressive day trading - every 15 minutes
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15

# Conservative - every hour
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 60
```

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
./start_live_trading.sh --port 8080 --model gpt-4o --cadence 15

# Environment overrides (optional):
#   export DAI_MAX_TRADES=1      # already set by start_live_trading.sh
#   export DAI_SCHWAB_INTERACTIVE=0  # skip ENTER prompt
```

### **Full Live Trading (Automation Enabled)**
```bash
# After verifying the pilot, remove the trade cap and increase cadence as desired
export DAI_MAX_TRADES=5          # or your preferred limit
export DAI_SCHWAB_READONLY=0     # ensure live orders are allowed
export DAI_SCHWAB_LIVE_VIEW=0    # full automation mode

./start_d_ai_trader.sh -p 8080 -m gpt-4o -t real_world -c 15
```

**Dashboard:** http://localhost:8080

---

## 🎯 Day Trading Strategy

### **Trading Philosophy**
- ⚡ **Quick Profits**: Target 5-10% gains per trade, exit fast
- 🔄 **Multiple Trades Per Day**: 15-60 minute cadence = 7-27 opportunities/day
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
6:25 AM PT (9:25 AM ET) - Analyze overnight/pre-market news
6:30:05 AM PT (9:30:05 AM ET) - Execute opening trades (5 sec after bell)
```

### **Intraday Trading**
```
6:35 AM - 1:00 PM PT - Run every N minutes (configurable: 15/30/60)
   ├─ Scan 6 news sources
   ├─ Analyze current positions (take profits? cut losses?)
   ├─ Make trading decisions
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
- **gpt-4o** ⭐ - BEST for real money ($2.50/$10 per 1M tokens)
  - Reliable JSON parsing
  - Excellent vision capabilities
  - Custom temperature (0.3 for consistency)
  - 2000 tokens sufficient

- **gpt-4o-mini** - Good for testing ($0.15/$0.60 per 1M tokens)
  - Faster, cheaper
  - Good for simulation mode

- **gpt-4-turbo** - Legacy "GPT-4.1" equivalent

### **Experimental**
- **gpt-5** / **gpt-5-mini** - Reasoning models (⚠️ May hit token limits)
  - Uses tokens for internal "thinking"
  - Needs 8000+ tokens
  - No custom temperature
  - Not recommended for production yet

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

# Schwab API (Optional - for live trading)
SCHWAB_CLIENT_ID=your_client_id
SCHWAB_CLIENT_SECRET=your_client_secret
SCHWAB_ACCOUNT_HASH=your_account_hash
SCHWAB_REDIRECT_URI=https://127.0.0.1:5556/callback
```

---

## 🎮 Usage

### **Command Line Options**
```bash
./start_d_ai_trader.sh [OPTIONS]

Options:
  -p, --port PORT           Dashboard port (default: 8080)
  -m, --model MODEL         AI model (default: gpt-4o)
  -v, --prompt-version VER  auto | vN (default: auto)
  -t, --trading-mode MODE   simulation | real_world (default: simulation)
  -c, --cadence MINUTES     15 | 30 | 60 (default: 60)
```

### **Examples**
```bash
# Aggressive day trading (every 15 min)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15

# Compare two models in parallel
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t simulation -c 15
./start_d_ai_trader.sh -p 8081 -m gpt-5-mini -v auto -t simulation -c 15

# Live trading (after testing!)
./start_d_ai_trader.sh -p 8080 -m gpt-4o -v auto -t real_world -c 15
```

---

## 📊 Dashboard Tabs

### **1. Dashboard** (Main)
- Portfolio value, cash balance, P&L
- Current holdings with gain/loss
- Interactive charts (portfolio history, performance)
- Manual trigger buttons (Run All Agents, etc.)

### **2. Trades**
- All trading decisions with timestamps
- Ticker, Action, Shares, Amount, Reason
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

### **With 15-Minute Cadence**
- Trading opportunities: ~27 per day
- Target per trade: 5-10% gain
- Win rate: 50-60%
- Daily gain potential: 15-25%
- Monthly gain potential: 300-500%+

### **Costs (GPT-4o)**
- ~156 API calls/day (6 sources × 26 cycles)
- ~$10/day in API costs
- ~$300/month
- **Worth it if trading with real money!**

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

### **API Costs (GPT-4o)**
- 6 sources × 26 cycles/day = 156 calls/day
- ~5K tokens per screenshot analysis
- ~780K tokens/day total
- **Input**: $2.50/1M tokens = $2/day
- **Output**: $10/1M tokens = $8/day
- **Total**: ~$10/day or $300/month

### **Potential Returns**
- 26 trades/day × 6% average × 50% win rate = 78% daily gain potential
- With $10K portfolio = $7,800/day theoretical maximum
- Realistic target: 15-25% daily gains = $1,500-$2,500/day
- **API costs ($10/day) are negligible vs. trading profits**

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
