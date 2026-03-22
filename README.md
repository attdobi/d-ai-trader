# 🤖 D-AI-Trader

Autonomous stock trading system powered by **GPT-5.4**. Scrapes financial news via headless Chrome, runs it through AI summarization and decision-making, and executes trades through the Schwab API — or in simulation mode with no broker required.

Default cadence is **3 hours** (180 min), targeting 1–3 day hold periods suited to **cash accounts** (T+1 settlement). Margin accounts ($25k+) can run faster cadences.

---

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.12+ | 3.14 tested |
| PostgreSQL 17 | Optional — falls back to SQLite |
| Chrome 141+ | Headless scraping |
| OpenAI API key | Required |
| Schwab API creds | Only for live trading |

### 1. Clone & Configure

```bash
git clone <repo-url>
cd d-ai-trader
cp env_template.txt .env
# Edit .env — at minimum set OPENAI_API_KEY
```

### 2. Database (optional)

```bash
brew install postgresql@17 && brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
createdb adobi
# Add to .env:
#   DATABASE_URI=postgresql://$(whoami)@localhost/adobi
python init_database.py
```

Skip this and the app boots on SQLite automatically.

### 3. Run in Simulation

```bash
# Default 3-hour cadence, GPT-5.4
./start_d_ai_trader.sh -p 8080 -t simulation -c 180

# Faster loops for experimentation
./start_d_ai_trader.sh -p 8080 -t simulation -c 60
./start_d_ai_trader.sh -p 8080 -t simulation -c 15
```

The launcher auto-creates a virtualenv and installs dependencies on first run.

**Dashboard:** http://localhost:8080

---

## Architecture

```
Summarizer  →  Momentum Recap  →  Decider  →  Execution  →  Feedback
(6 sources)    (scorable view)    (GPT-5.4)   (sim/Schwab)  (post-close)
```

### Pipeline Detail

```
              Every cadence cycle (first at market open 6:30 AM PT)
                                │
                                ▼
                   ┌─────────────────────┐
                   │     Summarizer      │
                   │  6 news sources →   │
                   │  screenshot + GPT   │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │   Momentum Recap    │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │      Decider        │
                   │  BUY / SELL / HOLD  │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │   Decision Validator│
                   │  (guardrails)       │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  Execution Layer    │
                   │  simulation │ Schwab│
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  Feedback Agent     │
                   │  (daily post-close) │
                   └─────────────────────┘
```

### Core Modules

| File | Purpose |
|---|---|
| `d_ai_trader.py` | Main orchestrator + scheduler |
| `main.py` | News scraping & screenshot analysis |
| `decider_agent.py` | Trading decision engine |
| `decision_validator.py` | Financial guardrails — prevents hallucinated trades |
| `feedback_agent.py` | Post-close performance analysis |
| `config.py` | Model config, env loading, DB setup |
| `dashboard_server.py` | Flask web UI + API |
| `schwab_client.py` | Schwab API integration |
| `schwab_streaming.py` | Real-time Level-One quotes + account activity |
| `schwab_ledger.py` | Shadow ledger for unsettled cash tracking |
| `trading_interface.py` | Unified sim/live trading layer |
| `safety_checks.py` | Multi-layer safety manager |
| `prompt_manager.py` | Prompt versioning & evolution |
| `shared/market_clock.py` | Market hours utility |
| `shared/run_context.py` | Run context propagation |
| `shared/ticker_normalize.py` | Consistent ticker handling |

---

## Configuration

### `.env` Reference

```bash
# Required
OPENAI_API_KEY=sk-proj-your_key_here

# Model (default: gpt-5.4)
DAI_GPT_MODEL=gpt-5.4

# Database (optional — falls back to SQLite)
DATABASE_URI=postgresql://$(whoami)@localhost/adobi

# Account type
IS_MARGIN_ACCOUNT=0          # 0 = cash (default), 1 = margin ($25k+ only)

# Trading
TRADING_MODE=simulation      # simulation | live
MAX_POSITION_VALUE=2000      # Per-position floor ($)
MAX_POSITION_FRACTION=0.33   # Per-position fraction of account
MAX_TOTAL_INVESTMENT=10000   # Total invested capital floor ($)
MAX_TOTAL_INVESTMENT_FRACTION=0.95
MIN_CASH_BUFFER=500          # Minimum cash reserve ($)
DAI_MAX_TRADES=4             # Max trades per cycle (buys + sells)
DAI_MODEL_TEMPERATURE=0.3

# Reasoning levels (light | medium | high)
DAI_SUMMARIZER_REASONING_LEVEL=medium
DAI_DECIDER_REASONING_LEVEL=high
DAI_FEEDBACK_REASONING_LEVEL=high

# Schwab API (for live trading)
SCHWAB_CLIENT_ID=your_client_id
SCHWAB_CLIENT_SECRET=your_client_secret
SCHWAB_ACCOUNT_HASH=your_account_hash
SCHWAB_REDIRECT_URI=https://127.0.0.1:5556/callback

# Optional
DAI_PROMPT_PROFILE=standard  # standard | gpt-pro
DAI_DECIDER_RAW_PREVIEW=4000 # Debug: chars of raw Decider output to print
```

### CLI Options

```
./start_d_ai_trader.sh [OPTIONS]

  -p, --port PORT            Dashboard port (default: 8080)
  -m, --model MODEL          AI model (default: gpt-5.4)
  -v, --prompt-version VER   auto | vN (default: auto)
  -P, --prompt-profile PROF  standard | gpt-pro (default: standard)
  -t, --trading-mode MODE    simulation | live (default: simulation)
  -c, --cadence MINUTES      180 (default) | 60 | 30 | 15
```

### Supported Models

| Model | Use Case | Notes |
|---|---|---|
| **gpt-5.4** ⭐ | Default for all agents | Reasoning + vision, auto-fallback to gpt-4.1 |
| **gpt-5.2** | Alternative reasoning | Slightly lower cost than 5.4 |
| **gpt-5.1** | Legacy default | Still fully supported |
| **gpt-4o** | Budget option | $2.50/$10 per 1M tokens, reliable JSON |
| **gpt-4.1** | Fallback model | Auto-selected when 5.x fails |
| **gpt-4o-mini** | Cheap testing | $0.15/$0.60 per 1M tokens, simulation only |

> o1/o3 models are **not** supported (no system messages or JSON mode).

---

## Trading Strategy

### Philosophy

- **Selective entries**: 2–3 high-conviction trades per day at 3-hour cadence
- **Quick profits**: Target 5–10% gains, exit fast
- **Momentum-based**: Ride trends, cut before reversals
- **Capital rotation**: Sell winners, redeploy into new opportunities

### Profit Targets & Stop Losses

| Condition | Action |
|---|---|
| +5–8% | SELL — lock in profit |
| +8–15% | SELL — great trade |
| +15%+ | SELL NOW — exceptional |
| −3% to −5% | SELL — stop loss, protect capital |

### Position Sizing

- Per trade: $1,500–$4,000
- Max concurrent positions: 5
- Cash buffer always maintained

### Account Types

- **Cash (default, `IS_MARGIN_ACCOUNT=0`)**: Buys use settled funds only. T+1 settlement means 1–3 day hold periods. The 3-hour cadence keeps you compliant with good-faith rules.
- **Margin (`IS_MARGIN_ACCOUNT=1`)**: Reuses same-day proceeds. Requires $25k+ to avoid PDT violations. Enables faster cadences (15–30 min).

---

## Schedule

| Time (PT) | Event |
|---|---|
| 6:30 AM | Market open — first cycle runs |
| 6:30 AM → 1:00 PM | Intraday cycles every `--cadence` minutes |
| 1:00 PM | Market close |
| 1:30 PM | Feedback agent runs daily analysis |
| After hours | Decisions recorded as "⛔ MARKET CLOSED", no execution |

The scheduler auto-runs a catch-up cycle if started after 6:30 AM PT.

---

## News Sources

| Source | Focus |
|---|---|
| Yahoo Finance | Stock news, earnings |
| Benzinga ⭐ | Day trading catalysts, movers |
| Fox Business | Market sentiment |
| AP Business | Clean, factual |
| BBC Business | International markets |
| CNBC | Breaking news, market movers |

All work with headless Chrome — no bot detection issues.

---

## Dashboard

**Tabs:**

- **Dashboard** — Portfolio value, cash balance, P&L, interactive charts. Schwab card shows settled vs raw cash, funds-available components, margin indicator.
- **Trades** — All decisions with timestamps, tickers (linked to Yahoo Finance with chart popups), config-specific filtering.
- **Summaries** — Latest news analysis from all 6 sources, timestamped PT.
- **Feedback** — Win rate, average profit, trade outcomes, AI learning insights.
- **Schwab** — Live account balance, holdings, buying power, real-time sync.
- **Prompt Lab** — Interactive prompt evolution and testing.

Manual trigger buttons: Run Summarizer, Run Decider, Run Feedback, Run All Agents.

---

## Live Trading

### Step 1: Read-Only Schwab Test

```bash
./start_schwab_live_view.sh -p 8080
# Open http://localhost:8080/schwab
```

### Step 2: Single-Buy Pilot

```bash
./start_live_trading.sh --port 8080 --model gpt-5.4 --cadence 180
# Executes at most ONE buy per cycle
```

### Step 3: Full Automation

```bash
export DAI_MAX_TRADES=5
export DAI_SCHWAB_READONLY=0
./start_d_ai_trader.sh -p 8080 -t real_world -c 180
```

### OAuth & Token Management

```bash
# Manual OAuth flow
SCHWAB_CLIENT_ID=... SCHWAB_CLIENT_SECRET=... ./schwab_manual_auth.py --save

# Refresh existing token
SCHWAB_CLIENT_ID=... SCHWAB_CLIENT_SECRET=... ./schwab_manual_auth.py --refresh --save
```

> Schwab refresh tokens expire ~7 days. If you see `refresh_token_authentication_error`, delete `schwab_tokens.json`, re-run the OAuth flow via `./test_schwab_api.sh`, and restart.

### Streaming (Live Quotes)

```bash
# Auto-detect symbols from current positions
./run_schwab_streaming.py

# Custom watchlist
DAI_STREAM_SYMBOLS="SPY,AAPL,QQQ" ./run_schwab_streaming.py
```

The streaming helper maintains a shadow ledger so effective funds update immediately after fills. Launched automatically by `start_live_trading.sh`; add `--no-stream` to disable.

---

## Guardrails

### Decision Validator

- Cannot sell stocks you don't own
- Cannot buy stocks you already hold
- Enforces position size limits
- Validates tickers and amounts against current portfolio

### Multi-Layer Safety (Live)

1. `DAI_SCHWAB_READONLY` flag
2. `TRADING_MODE` must be `live`
3. Market hours enforcement
4. Decision validator approval
5. Safety manager checks

### Emergency Stop

```bash
pkill -f d_ai_trader.py
pkill -f dashboard_server.py
```

---

## Parallel Runs

Each configuration gets a unique `config_hash` — data is fully isolated:

```bash
# Terminal 1
./start_d_ai_trader.sh -p 8080 -m gpt-5.4 -t simulation -c 180

# Terminal 2 — different model, different port
./start_d_ai_trader.sh -p 8081 -m gpt-4o -t simulation -c 60
```

---

## Cost Estimate

### API Usage (default 3-hour cadence, GPT-4o pricing)

- 6 sources × 3 cycles/day ≈ 18 vision calls
- ~90K tokens/day
- **~$1/day** (~$30/month)

GPT-5.4 costs more per token but uses fewer cycles. Actual spend depends on cadence and model choice.

---

## Project Structure

```
d-ai-trader/
├── d_ai_trader.py              # Orchestrator + scheduler
├── main.py                     # News scraping
├── decider_agent.py            # Trading decisions
├── decision_validator.py       # Guardrails
├── feedback_agent.py           # Performance analysis
├── dashboard_server.py         # Web UI + API
├── config.py                   # Configuration
├── schwab_client.py            # Schwab API
├── schwab_streaming.py         # Live quotes
├── schwab_ledger.py            # Shadow ledger
├── trading_interface.py        # Unified trading layer
├── safety_checks.py            # Safety manager
├── prompt_manager.py           # Prompt versioning
├── init_database.py            # Schema setup
├── shared/
│   ├── market_clock.py         # Market hours utility
│   ├── run_context.py          # Run context propagation
│   └── ticker_normalize.py     # Ticker normalization
├── prompts/                    # Prompt templates
├── templates/                  # Flask HTML templates
├── static/                     # Frontend assets
├── tests/                      # Test suite
├── screenshots/                # Captured news screenshots
├── start_d_ai_trader.sh        # Main launcher
├── start_live_trading.sh       # Live trading launcher
├── start_schwab_live_view.sh   # Read-only Schwab viewer
├── .env                        # Local config (not committed)
└── env_template.txt            # .env template
```

---

## Documentation

| File | Contents |
|---|---|
| `GO_LIVE_CHECKLIST.md` | Pre-flight safety checklist |
| `SCHWAB_API_SETUP.md` | Schwab API configuration |
| `SCHWAB_READONLY_TEST.md` | Safe broker testing |
| `FEEDBACK_SYSTEM.md` | AI learning system |
| `AUTOMATION_README.md` | Scheduling & automation |
| `SETUP_DEPENDENCIES.md` | Dependency setup |

---

## Troubleshooting

**ChromeDriver mismatch** — System auto-detects Chrome version and downloads the matching driver. Restart if you see version errors after a Chrome update.

**API key errors** — Check `.env` for stray characters (trailing `$`, extra quotes). Run with `PRINT_OPENAI_KEY=1` to see the masked key at startup.

**"MARKET CLOSED" decisions** — Normal outside 9:30 AM–4:00 PM ET (Mon–Fri). Decisions are recorded but not executed.

**Schwab token expired** — Delete `schwab_tokens.json`, re-run OAuth via `./test_schwab_api.sh`, restart.

---

## ⚠️ Disclaimer

Day trading is risky. You can lose money. This is experimental software for educational purposes. Start in simulation, test thoroughly, and never trade with money you can't afford to lose. This is not financial advice.

---

## Changelog

### March 2026
- Upgraded default model to GPT-5.4
- Frontend overhaul — premium fintech dark theme
- Added `init_database.py` for proper schema initialization
- Prompt Lab tab — interactive prompt evolution dashboard
- Extracted `MarketClock` utility + test suite
- Codebase cleanup (−450 lines)
- Centralized run context propagation
- Shared ticker normalization

### December 2025
- Prompt profile flag (`-P/--prompt-profile`)
- Trades tab: Yahoo Finance links + chart popups
- Schwab card: settled funds / raw cash / margin differentiation
- `DAI_DECIDER_RAW_PREVIEW` for raw output debugging
- Scheduler catch-up if started after market open

### October 2025
- GPT-4o Vision for screenshot analysis
- GPT-5 reasoning model support
- Configurable cadence (15/30/60/180 min)
- Financial guardrails (AI hallucination prevention)
- Config-isolated parallel runs
- 6 reliable news sources
- Schwab read-only testing mode
