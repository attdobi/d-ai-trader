# --- D-AI-Trader bootstrap (auto-inserted) ---
import os as _os, sys as _sys
_repo_root = _os.environ.get("DAI_TRADER_ROOT") or _os.path.dirname(_os.path.abspath(__file__))
_os.environ.setdefault("DAI_TRADER_ROOT", _repo_root)
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
_os.environ.setdefault("DAI_DISABLE_UC", "1")
try:
    import sitecustomize  # noqa: F401
except Exception:
    pass
# --- end bootstrap ---

import json
import os
import pytz
from datetime import datetime
import time
import threading
import atexit
from math import floor
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import lru_cache
from typing import Dict, Any
import pandas as pd
import re
from sqlalchemy import text
from config import (
    engine,
    PromptManager,
    session,
    openai,
    get_current_config_hash,
    get_trading_mode,
    set_gpt_model,
    IS_MARGIN_ACCOUNT,
    DAILY_TICKET_CAP,
    DAILY_BUY_CAP,
    MIN_ENTRY_SPACING_MIN,
    REENTRY_COOLDOWN_MIN,
)
import yfinance as yf
from feedback_agent import TradeOutcomeTracker

# Apply model from environment if specified
if _os.environ.get("DAI_GPT_MODEL"):
    set_gpt_model(_os.environ["DAI_GPT_MODEL"])

# Timezone configuration
PACIFIC_TIMEZONE = pytz.timezone('US/Pacific')
EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

# Trading configuration
try:
    MAX_TRADES = max(1, int(_os.getenv("DAI_MAX_TRADES", "5")))
except (TypeError, ValueError):
    MAX_TRADES = 5
MAX_FUNDS = 10000
MIN_BUFFER = 100  # Must always have at least this much left
MIN_BUY_AMOUNT = float(_os.getenv("DAI_MIN_BUY_AMOUNT", "1000"))
TYPICAL_BUY_LOW = float(_os.getenv("DAI_TYPICAL_BUY_LOW", "2000"))
TYPICAL_BUY_HIGH = float(_os.getenv("DAI_TYPICAL_BUY_HIGH", "3500"))
MAX_BUY_AMOUNT = float(_os.getenv("DAI_MAX_BUY_AMOUNT", "4000"))
SUMMARY_MAX_CHARS = int(_os.getenv("DAI_SUMMARY_CHARS", "3000"))
ONE_TRADE_MODE = int(_os.getenv("DAI_ONE_TRADE_MODE", "0"))
_profit_threshold_env = _os.getenv("DAI_FORCE_PROFIT_MIN_PCT") or _os.getenv("DAI_PROFIT_TAKE_MIN_PCT") or "3.0"
try:
    PROFIT_ENFORCEMENT_MIN_PCT = max(0.0, float(_profit_threshold_env))
except (TypeError, ValueError):
    PROFIT_ENFORCEMENT_MIN_PCT = 3.0
PROFIT_ENFORCEMENT_ENABLED = (_os.getenv("DAI_FORCE_PROFIT_TAKING", "1").strip().lower() not in {"0", "false", "off", "no"})

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

# Initialize feedback tracker
feedback_tracker = TradeOutcomeTracker()


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _holding_gain_pct(holding):
    purchase_price = _safe_float(holding.get("purchase_price"))
    current_price = _safe_float(holding.get("current_price"))
    if purchase_price > 0 and current_price > 0:
        return ((current_price - purchase_price) / purchase_price) * 100.0
    total_value = _safe_float(holding.get("total_value"))
    gain_loss = _safe_float(holding.get("gain_loss"))
    if total_value > 0:
        return (gain_loss / total_value) * 100.0
    return 0.0


def _holding_current_value(holding):
    current_value = _safe_float(holding.get("current_value"))
    if current_value > 0:
        return current_value
    shares = _safe_float(holding.get("shares"))
    current_price = _safe_float(holding.get("current_price"))
    if shares > 0 and current_price > 0:
        return shares * current_price
    fallback = _safe_float(holding.get("total_value"))
    if fallback > 0:
        return fallback
    return 0.0


def enforce_profit_taking_guardrail(decisions, holdings_by_ticker, threshold_pct=PROFIT_ENFORCEMENT_MIN_PCT):
    """
    Ensure ≥threshold winners are converted to SELL actions even if the model resists.
    Returns a list of human-readable override summaries.
    """
    if not PROFIT_ENFORCEMENT_ENABLED or not holdings_by_ticker or not isinstance(decisions, list):
        return []

    forced = []
    for ticker, holding in holdings_by_ticker.items():
        gain_pct = _holding_gain_pct(holding)
        if gain_pct < threshold_pct:
            continue

        decision = None
        for candidate in decisions:
            if isinstance(candidate, dict) and (candidate.get("ticker") or "").upper() == ticker:
                decision = candidate
                break

        existing_action = (decision.get("action") or "").lower() if decision else ""
        if existing_action == "sell":
            continue

        if decision is None:
            decision = {"ticker": ticker}
            decisions.append(decision)

        amount_value = _holding_current_value(holding)
        basis_val = _safe_float(holding.get("purchase_price"))
        basis_text = f"${basis_val:.2f}" if basis_val > 0 else "basis n/a"
        forced_reason = (
            f"Forced SELL {ticker}: +{gain_pct:.1f}% vs {basis_text} cost. "
            "Profit-taking guardrail frees settled funds for the next GPT-5.1 regular cycle."
        )
        combined_reason = forced_reason
        if existing_action and decision.get("reason"):
            original_reason = decision.get("reason").strip()
            if original_reason:
                combined_reason = f"{original_reason} — {forced_reason}"

        decision.update({
            "action": "sell",
            "amount_usd": amount_value,
            "reason": combined_reason,
            "enforced": "profit_guardrail",
        })
        shares = _safe_float(holding.get("shares"))
        if shares > 0:
            decision["shares"] = shares

        forced.append(f"{ticker} +{gain_pct:.1f}% (overrode {existing_action or 'none'})")
        print(f"🚨 Profit-taking guardrail: overriding {ticker} decision ({existing_action or 'missing'}) with SELL at +{gain_pct:.1f}%")

    return forced


def store_momentum_snapshot(config_hash, run_id, companies, momentum_data, momentum_summary, momentum_recap):
    """Persist momentum recap information for reuse in UI displays, keyed by summarizer run."""
    if not config_hash or not run_id:
        return

    try:
        companies_json = json.dumps(companies or [])
    except Exception:
        companies_json = json.dumps([])

    try:
        momentum_json = json.dumps(momentum_data or [])
    except Exception:
        momentum_json = json.dumps([])

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS momentum_snapshots (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                run_id TEXT NOT NULL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                companies_json JSONB,
                momentum_data JSONB,
                momentum_summary TEXT,
                momentum_recap TEXT
            )
        """))
        conn.execute(text("""
            ALTER TABLE momentum_snapshots
            ADD COLUMN IF NOT EXISTS run_id TEXT
        """))

        conn.execute(text("""
            INSERT INTO momentum_snapshots (
                config_hash,
                run_id,
                generated_at,
                companies_json,
                momentum_data,
                momentum_summary,
                momentum_recap
            ) VALUES (
                :config_hash,
                :run_id,
                :generated_at,
                :companies_json,
                :momentum_data,
                :momentum_summary,
                :momentum_recap
            )
        """), {
            "config_hash": config_hash,
            "run_id": run_id,
            "generated_at": datetime.now(PACIFIC_TIMEZONE).astimezone(pytz.UTC).replace(tzinfo=None),
            "companies_json": companies_json,
            "momentum_data": momentum_json,
            "momentum_summary": momentum_summary or "",
            "momentum_recap": momentum_recap or "",
        })



def get_daily_trade_usage(config_hash: str) -> Dict[str, Any]:
    """Summarize today's recorded decisions for pacing logic."""
    now_pacific = datetime.now(PACIFIC_TIMEZONE)
    day_start = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_naive = day_start.replace(tzinfo=None)

    today_tickets = 0
    today_buys = 0
    last_entry_ts = None
    tickers_entered: set[str] = set()

    with engine.begin() as conn:
        rows = conn.execute(text(
            """
            SELECT timestamp, data
            FROM trade_decisions
            WHERE config_hash = :config_hash
              AND timestamp >= :day_start
            """
        ), {"config_hash": config_hash, "day_start": day_start_naive}).fetchall()

    for row in rows:
        decisions_payload = row.data
        if isinstance(decisions_payload, str):
            try:
                decisions_payload = json.loads(decisions_payload)
            except json.JSONDecodeError:
                continue

        if isinstance(decisions_payload, dict) and "decisions" in decisions_payload:
            decisions = decisions_payload.get("decisions", [])
        else:
            decisions = decisions_payload

        if not isinstance(decisions, list):
            continue

        today_tickets += len(decisions)
        ts = row.timestamp
        ts_local = None
        if isinstance(ts, datetime):
            ts_local = ts if ts.tzinfo else PACIFIC_TIMEZONE.localize(ts)
            if ts_local.tzinfo:
                ts_local = ts_local.astimezone(PACIFIC_TIMEZONE)

        for decision in decisions:
            action = (decision.get("action") or "").lower()
            ticker = (decision.get("ticker") or "").upper()
            amount = float(decision.get("amount_usd", 0) or 0)
            if action == "buy" and amount > 0:
                today_buys += 1
                if ticker:
                    tickers_entered.add(ticker)
                if ts_local and (last_entry_ts is None or ts_local > last_entry_ts):
                    last_entry_ts = ts_local

    minutes_since_entry = None
    if last_entry_ts:
        minutes_since_entry = max(0, int((now_pacific - last_entry_ts).total_seconds() // 60))

    return {
        "today_tickets_used": today_tickets,
        "today_buys_used": today_buys,
        "minutes_since_last_entry": minutes_since_entry,
        "tickers_entered_today": sorted(tickers_entered),
    }


class YFinancePriceFetcher:
    """Shared price fetcher that caches results and batches slow Yahoo Finance calls."""

    def __init__(self, cache_ttl_seconds=None, max_workers=None):
        self._cache_ttl = float(cache_ttl_seconds or _os.getenv("PRICE_CACHE_TTL", "60"))
        self._executor = ThreadPoolExecutor(max_workers=max(2, int(max_workers or _os.getenv("PRICE_FETCHER_WORKERS", "4"))))
        self._cache = {}
        self._lock = threading.Lock()
        atexit.register(self._shutdown)

    def _shutdown(self):
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

    def _cache_get(self, ticker):
        now = time.time()
        with self._lock:
            cached = self._cache.get(ticker)
            if not cached:
                return None
            price, ts = cached
            if price is not None and now - ts <= self._cache_ttl:
                return price
            # Expired cache entry
            self._cache.pop(ticker, None)
            return None

    def _cache_set(self, ticker, price):
        with self._lock:
            self._cache[ticker] = (price, time.time())

    def _run_with_timeout(self, func, timeout_seconds):
        future = self._executor.submit(func)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError:
            future.cancel()
            raise

    @staticmethod
    def _is_valid_price(value):
        try:
            return value is not None and float(value) > 0
        except (TypeError, ValueError):
            return False

    def _fetch_from_info(self, stock, ticker):
        try:
            info = self._run_with_timeout(lambda: stock.info, 10)
        except TimeoutError:
            print(f"⏰ {ticker}: Price info timeout after 10 seconds")
            return None
        except Exception as e:
            print(f"⚠️  {ticker}: Failed to load info: {e}")
            return None

        if not isinstance(info, dict):
            return None

        for field, label in (
            ("currentPrice", "current price"),
            ("regularMarketPrice", "regular market price"),
            ("previousClose", "previous close"),
        ):
            value = info.get(field)
            if self._is_valid_price(value):
                price = float(value)
                print(f"✅ {ticker}: Got {label}: ${price:.2f}")
                return price
        return None

    def _fetch_from_fast_info(self, stock, ticker):
        try:
            fast_info = getattr(stock, "fast_info", None)
        except Exception:
            fast_info = None

        if not fast_info:
            return None

        for key in ("lastPrice", "regularMarketPrice", "regularMarketPreviousClose"):
            value = None
            try:
                value = fast_info.get(key) if hasattr(fast_info, "get") else getattr(fast_info, key, None)
            except Exception:
                value = None
            if self._is_valid_price(value):
                price = float(value)
                print(f"✅ {ticker}: Got price from fast_info {key}: ${price:.2f}")
                return price
        return None

    def _fetch_from_history(self, stock, ticker):
        try:
            history = self._run_with_timeout(lambda: stock.history(period="5d", interval="1d", prepost=True), 15)
        except TimeoutError:
            print(f"⏰ {ticker}: History fetch timeout after 15 seconds")
            return None
        except Exception as e:
            print(f"⚠️  {ticker}: History fetch failed: {e}")
            return None

        if history is None or history.empty:
            return None

        close_series = history["Close"] if "Close" in history.columns else None
        if close_series is None:
            return None

        last_valid = close_series.dropna()
        if last_valid.empty:
            return None

        price = float(last_valid.iloc[-1])
        print(f"✅ {ticker}: Got price from 5d history: ${price:.2f}")
        return price

    def _fetch_from_download(self, ticker):
        try:
            data = self._run_with_timeout(
                lambda: yf.download(
                    tickers=ticker,
                    period="1mo",
                    interval="1d",
                    prepost=True,
                    progress=False,
                ),
                20,
            )
        except TimeoutError:
            print(f"⏰ {ticker}: yf.download timeout after 20 seconds")
            return None
        except Exception as e:
            print(f"⚠️  {ticker}: yf.download failed: {e}")
            return None

        if data is None or data.empty:
            return None

        close_series = data["Close"] if "Close" in data.columns else data.get(("Close", ticker))
        if close_series is None:
            return None

        last_valid = close_series.dropna()
        if last_valid.empty:
            return None

        price = float(last_valid.iloc[-1])
        print(f"✅ {ticker}: Got price from yf.download 1mo: ${price:.2f}")
        return price

    def _fetch_price(self, ticker):
        stock = yf.Ticker(ticker)
        price = self._fetch_from_info(stock, ticker)
        if self._is_valid_price(price):
            return float(price)

        price = self._fetch_from_fast_info(stock, ticker)
        if self._is_valid_price(price):
            return float(price)

        price = self._fetch_from_history(stock, ticker)
        if self._is_valid_price(price):
            return float(price)

        price = self._fetch_from_download(ticker)
        if self._is_valid_price(price):
            return float(price)

        return None

    def get_price(self, ticker):
        ticker = ticker.upper()
        cached = self._cache_get(ticker)
        if self._is_valid_price(cached):
            print(f"✅ {ticker}: Using cached price ${float(cached):.2f}")
            return float(cached)

        price = self._fetch_price(ticker)
        if self._is_valid_price(price):
            self._cache_set(ticker, float(price))
            return float(price)

        return None

    def prefetch_prices(self, tickers):
        unique = sorted({t.upper() for t in tickers if t})
        if len(unique) <= 1:
            # Single tickers handled lazily
            return

        pending = [t for t in unique if self._cache_get(t) is None]
        if not pending:
            return

        try:
            data = self._run_with_timeout(
                lambda: yf.download(
                    tickers=pending,
                    period="5d",
                    interval="1d",
                    prepost=True,
                    progress=False,
                    group_by="ticker",
                    threads=False,
                ),
                20,
            )
        except TimeoutError:
            print(f"⏰ Bulk price fetch timeout for {pending}")
            return
        except Exception as e:
            print(f"⚠️  Bulk price fetch failed for {pending}: {e}")
            return

        if data is None or data.empty:
            return

        if getattr(data.columns, "nlevels", 1) > 1:
            try:
                close_frame = data["Close"]
            except KeyError:
                close_frame = None
            if close_frame is not None:
                for ticker in close_frame.columns:
                    series = close_frame[ticker].dropna()
                    if not series.empty:
                        self._cache_set(ticker.upper(), float(series.iloc[-1]))
        else:
            close_series = data["Close"] if "Close" in data.columns else None
            if close_series is not None:
                last_valid = close_series.dropna()
                if not last_valid.empty:
                    self._cache_set(unique[0], float(last_valid.iloc[-1]))


price_fetcher = YFinancePriceFetcher()

def is_market_open():
    """Check if the market is currently open (M-F, 9:30am-4pm ET)"""
    # Get current time in Pacific, convert to Eastern for market hours check
    now_pacific = datetime.now(PACIFIC_TIMEZONE)
    now_eastern = now_pacific.astimezone(EASTERN_TIMEZONE)
    
    # Check if it's a weekday (Monday = 0, Sunday = 6)
    if now_eastern.weekday() >= 5:  # Saturday or Sunday
        return False
        
    # Check if it's within market hours (Eastern Time)
    market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return market_open <= now_eastern <= market_close

def get_latest_run_id():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT run_id FROM summaries
            WHERE config_hash = :config_hash
            ORDER BY timestamp DESC LIMIT 1
        """), {"config_hash": get_current_config_hash()}).fetchone()
        return result[0] if result else None

def fetch_summaries(run_id):
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT agent, data FROM summaries
            WHERE run_id = :run_id AND config_hash = :config_hash
        """), {"run_id": run_id, "config_hash": get_current_config_hash()})
        return [row._mapping for row in result]

def get_unprocessed_summaries():
    """Get all summaries that haven't been processed by the decider yet"""
    with engine.connect() as conn:
        # Get all summaries that haven't been processed
        result = conn.execute(text("""
            SELECT s.id, s.agent, s.timestamp, s.run_id, s.data
            FROM summaries s
            LEFT JOIN processed_summaries ps ON s.id = ps.summary_id AND ps.processed_by = 'decider'
            WHERE ps.summary_id IS NULL
            ORDER BY s.timestamp ASC
        """))
        return [row._mapping for row in result]

def mark_summaries_processed(summary_ids):
    """Mark summaries as processed by the decider"""
    with engine.begin() as conn:
        for summary_id in summary_ids:
            # Use Pacific time for run_id consistency
            pacific_now = datetime.now(PACIFIC_TIMEZONE)
            run_id_timestamp = pacific_now.strftime("%Y%m%dT%H%M%S")
            
            conn.execute(text("""
                INSERT INTO processed_summaries (summary_id, processed_by, run_id)
                VALUES (:summary_id, 'decider', :run_id)
            """), {
                "summary_id": summary_id,
                "run_id": run_id_timestamp
            })

def update_all_current_prices():
    """Update current prices for all active holdings before decision making"""
    print("=== Updating Current Prices for Decision Making ===")
    
    # Check market status
    market_open = is_market_open()
    if not market_open:
        print("⚠️  Market is currently CLOSED - using previous close prices")
        print("💡 For real-time prices, try during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)")
    else:
        print("✅ Market is OPEN - fetching real-time prices")
    
    with engine.begin() as conn:
        # Get all active holdings
        config_hash = get_current_config_hash()
        result = conn.execute(text("""
            SELECT ticker, shares, total_value, current_price
            FROM holdings 
            WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash
        """), {"config_hash": config_hash})
        
        holdings = [dict(row._mapping) for row in result]
        
        if not holdings:
            print("No active holdings to update.")
            return

        price_fetcher.prefetch_prices([holding["ticker"] for holding in holdings])
        
        updated_count = 0
        api_failures = []
        
        for holding in holdings:
            ticker = holding['ticker']
            shares = holding['shares']
            old_price = holding['current_price']
            
            # Get new price
            new_price = get_current_price(ticker)
            
            if new_price is None:
                print(f"⚠️  Could not get price for {ticker}, using last known price: ${old_price:.2f}")
                api_failures.append(ticker)
                continue
            
            # Calculate new values
            new_current_value = shares * new_price
            new_gain_loss = new_current_value - holding['total_value']
            
            # Update the database
            conn.execute(text("""
                UPDATE holdings
                SET current_price = :price,
                    current_value = :current_value,
                    gain_loss = :gain_loss,
                    current_price_timestamp = :timestamp
                WHERE ticker = :ticker AND config_hash = :config_hash
            """), {
                "price": new_price,
                "current_value": new_current_value,
                "gain_loss": new_gain_loss,
                "timestamp": datetime.utcnow(),
                "ticker": ticker,
                "config_hash": config_hash
            })
            
            print(f"✅ Updated {ticker}: ${old_price:.2f} → ${new_price:.2f} (Gain/Loss: ${new_gain_loss:.2f})")
            updated_count += 1
        
        print(f"Updated {updated_count} out of {len(holdings)} holdings")
        
        # If API failures occurred, provide manual update option
        if api_failures:
            print(f"\n🚨 API failures detected for: {', '.join(api_failures)}")
            print("💡 To manually update prices, run: python manual_price_update.py --interactive")
            print("💡 Or use: python manual_price_update.py --show (to view current holdings)")

def fetch_holdings():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS holdings (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                ticker TEXT NOT NULL,
                shares FLOAT,
                purchase_price FLOAT,
                current_price FLOAT,
                purchase_timestamp TIMESTAMP,
                current_price_timestamp TIMESTAMP,
                total_value FLOAT,
                current_value FLOAT,
                gain_loss FLOAT,
                reason TEXT,
                is_active BOOLEAN,
                UNIQUE(config_hash, ticker)
            )
        """))

        # Get current configuration hash
        config_hash = get_current_config_hash()
        
        # Ensure cash row exists for this configuration
        result = conn.execute(text("SELECT 1 FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash"), 
                            {"config_hash": config_hash})
        if not result.fetchone():
            print(f"🚀 Initializing new configuration {config_hash} with ${MAX_FUNDS} cash")
            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                VALUES (:config_hash, 'CASH', 1, :initial_cash, :initial_cash, now(), now(), :initial_cash, :initial_cash, 0, 'Initial cash', TRUE)
            """), {"config_hash": config_hash, "initial_cash": MAX_FUNDS})
            
            # Create initial portfolio snapshot for new configuration
            print(f"📊 Recording initial portfolio snapshot for config {config_hash}")
            # Use inline approach to avoid transaction issues
            conn.execute(text("""
                INSERT INTO portfolio_history 
                (total_portfolio_value, cash_balance, total_invested, 
                 total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
                VALUES (:total_portfolio_value, :cash_balance, :total_invested, 
                        :total_profit_loss, :percentage_gain, :holdings_snapshot, :config_hash)
            """), {
                "total_portfolio_value": MAX_FUNDS,
                "cash_balance": MAX_FUNDS,
                "total_invested": 0,
                "total_profit_loss": 0,
                "percentage_gain": 0,
                "holdings_snapshot": json.dumps([{"ticker": "CASH", "current_value": MAX_FUNDS}]),
                "config_hash": config_hash
            })
            print(f"✅ Initial portfolio snapshot recorded successfully")

        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, total_value, current_value, gain_loss, reason, is_active FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash})
        return [row._mapping for row in result]

def clean_ticker_symbol(ticker):
    """Clean up ticker symbol to extract just the symbol"""
    if not ticker:
        return None
    
    # Common symbol corrections and company name mappings
    SYMBOL_CORRECTIONS = {
        # Circle Internet Financial
        'CIRCL': 'CRCL',
        
        # Alphabet/Google - use Class C (GOOG) as it's more commonly traded
        'GOOGL': 'GOOG',
        'GOOGLE': 'GOOG',
        'ALPHABET': 'GOOG',
        
        # Meta/Facebook
        'FACEBOOK': 'META',
        'FB': 'META',
        
        # Tesla
        'TESLA': 'TSLA',
        
        # Apple
        'APPLE': 'AAPL',
        
        # Microsoft  
        'MICROSOFT': 'MSFT',
        
        # Amazon
        'AMAZON': 'AMZN',
        
        # Netflix
        'NETFLIX': 'NFLX',
        
        # NVIDIA
        'NVIDIA': 'NVDA',
        
        # Common ETFs
        'SP500': 'SPY',
        'S&P500': 'SPY',
        'S&P 500': 'SPY',
        'NASDAQ': 'QQQ',
        'NASDAQ100': 'QQQ',
        'NASDAQ 100': 'QQQ',
        
        # Add more corrections as needed
    }
    
    # Remove common prefixes/suffixes and extract just the symbol
    ticker = str(ticker).strip()
    
    # Handle cases like "S&P500 ETF (SPY)" -> "SPY"
    if '(' in ticker and ')' in ticker:
        # Extract text between parentheses
        start = ticker.rfind('(') + 1
        end = ticker.rfind(')')
        if start > 0 and end > start:
            ticker = ticker[start:end]
    
    # Remove common words that might be added by AI
    ticker = ticker.replace('ETF', '').replace('Stock', '').replace('Shares', '').strip()
    
    # Remove any remaining parentheses and clean up
    ticker = ticker.replace('(', '').replace(')', '').strip()
    
    # Apply symbol corrections
    ticker = SYMBOL_CORRECTIONS.get(ticker.upper(), ticker)
    
    return ticker

def validate_ticker_symbol(ticker):
    """Validate that a ticker symbol exists and can be traded"""
    import yfinance as yf
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        # Check if we can get basic info (name, sector, etc.)
        has_valid_data = info.get('symbol') == ticker.upper() or info.get('shortName') is not None
        
        return has_valid_data
    except Exception as e:
        print(f"⚠️  Ticker validation failed for {ticker}: {e}")
        print(f"🚫 Skipping trade due to validation failure")
        return False

def get_current_price(ticker):
    # Clean the ticker symbol first
    clean_ticker = clean_ticker_symbol(ticker)
    if not clean_ticker:
        print(f"Invalid ticker symbol: {ticker}")
        return None
    
    # Validate ticker exists before trying to get price
    if not validate_ticker_symbol(clean_ticker):
        print(f"🚫 Ticker {clean_ticker} does not exist or is not tradeable")
        return None
    
    try:
        price = price_fetcher.get_price(clean_ticker)
    except Exception as e:
        print(f"❌ Failed to fetch price for {clean_ticker} (original: {ticker}): {e}")
        return None

    if price is None:
        print(f"❌ All price fetching methods failed for {clean_ticker} (original: {ticker})")
        print("💡 This may be due to:")
        print("   - After market hours or weekend/holiday")
        print("   - Temporary Yahoo Finance API issues/rate limits")
        print("   - Symbol may be invalid or delisted")
        print("🚫 Yahoo Finance rate limit exceeded - skipping trade to ensure accurate pricing")
        print("💡 API rate limits typically clear within 1 hour")
        return None

    return float(price)


def _format_percent(value):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _format_number(value):
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "N/A"

    if abs(num) >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if abs(num) >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if abs(num) >= 1_000:
        return f"{num / 1_000:.2f}K"
    return f"{num:.0f}"


def _pct_change(current, reference):
    try:
        current = float(current)
        reference = float(reference)
    except (TypeError, ValueError):
        return None

    if reference == 0:
        return None
    return (current - reference) / reference * 100.0


PARENT_COMPANY_OVERRIDES = {
    # Streaming / digital platforms owned by Alphabet
    "youtube": {"company": "Alphabet", "symbol": "GOOGL"},
    "youtube tv": {"company": "Alphabet", "symbol": "GOOGL"},
    "google": {"company": "Alphabet", "symbol": "GOOGL"},

    # Disney media properties
    "abc": {"company": "The Walt Disney Company", "symbol": "DIS"},
    "espn": {"company": "The Walt Disney Company", "symbol": "DIS"},
    "disney+": {"company": "The Walt Disney Company", "symbol": "DIS"},
    "disney plus": {"company": "The Walt Disney Company", "symbol": "DIS"},

    # Meta platforms
    "instagram": {"company": "Meta Platforms", "symbol": "META"},
    "whatsapp": {"company": "Meta Platforms", "symbol": "META"},
    "oculus": {"company": "Meta Platforms", "symbol": "META"},

    # Microsoft products
    "linkedin": {"company": "Microsoft", "symbol": "MSFT"},
    "xbox": {"company": "Microsoft", "symbol": "MSFT"},

    # Amazon properties
    "prime video": {"company": "Amazon", "symbol": "AMZN"},
    "aws": {"company": "Amazon", "symbol": "AMZN"},
}


def safe_format_template(template: str, values: Dict[str, Any]) -> str:
    """Safely format templates that contain literal JSON braces."""
    sentinel_map = {}
    safe_template = template
    for key in values.keys():
        placeholder = f"{{{key}}}"
        marker = f"__PLACEHOLDER_{key.upper()}__"
        sentinel_map[marker] = key
        safe_template = safe_template.replace(placeholder, marker)

    safe_template = safe_template.replace('{', '{{').replace('}', '}}')

    for marker, key in sentinel_map.items():
        safe_template = safe_template.replace(marker, f"{{{key}}}")

    return safe_template.format(**values)


def _parse_company_entities(raw_response):
    """Attempt to parse company entities returned by the extraction agent."""
    if not raw_response:
        return []

    if isinstance(raw_response, list):
        return raw_response

    if isinstance(raw_response, dict):
        if 'companies' in raw_response and isinstance(raw_response['companies'], list):
            return raw_response['companies']
        # Some models may nest under a different key; fall back to dict values
        candidate = next((v for v in raw_response.values() if isinstance(v, list)), None)
        if candidate is not None:
            return candidate

    text = raw_response
    if not isinstance(text, str):
        try:
            text = json.dumps(raw_response)
        except Exception:
            text = str(raw_response)

    # Try direct JSON load
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            candidate = parsed.get('companies')
            if isinstance(candidate, list):
                return candidate
    except json.JSONDecodeError:
        pass

    # Attempt to extract the first JSON array in the text
    match = re.search(r"(\[[\s\S]*\])", text)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return []


def extract_companies_from_summaries(summary_text):
    """Use the CompanyExtractionAgent to pull companies and symbols from summaries."""
    if not summary_text.strip():
        return []

    try:
        from prompt_manager import get_active_prompt
        prompt_data = get_active_prompt("CompanyExtractionAgent")
        system_prompt = prompt_data["system_prompt"]
        user_prompt_template = prompt_data["user_prompt_template"]
        print(f"🧬 Using CompanyExtractionAgent prompt v{prompt_data.get('version', 'unknown')}")
    except Exception as e:
        print(f"⚠️  Falling back to default company extraction prompt: {e}")
        system_prompt = (
            "You extract company names and their stock tickers from market summaries. "
            "Map products, subsidiaries, or brands to their publicly traded parent company. "
            "Never guess tickers; if unsure, leave symbol blank. Return ONLY JSON."
        )
        user_prompt_template = (
            "Summaries discussing market activity:\n\n{summaries}\n\n"
            "Return a JSON array like [{\"company\": \"The Walt Disney Company\", \"symbol\": \"DIS\"}]. "
            "If a product or division is mentioned (e.g., YouTube TV, ESPN), list the parent company and "
            "its ticker symbol."
        )

    prompt = safe_format_template(user_prompt_template, {"summaries": summary_text})
    try:
        response = prompt_manager.ask_openai(prompt, system_prompt, agent_name="CompanyExtractionAgent")
    except Exception as exc:
        print(f"❌ Company extraction agent call failed: {exc}")
        return []
    entities = _parse_company_entities(response)

    cleaned_entities = []
    seen_symbols = set()
    seen_companies = set()
    for entry in entities:
        if not isinstance(entry, dict):
            continue

        company = (entry.get("company") or entry.get("name") or "").strip()
        symbol_raw = (entry.get("symbol") or entry.get("ticker") or "").strip()

        normalized_name = company.lower()
        override = PARENT_COMPANY_OVERRIDES.get(normalized_name)
        if override:
            company = override.get("company", company) or company
            symbol_raw = override.get("symbol", symbol_raw)

        symbol_display = symbol_raw.upper()
        normalized_symbol = clean_ticker_symbol(symbol_display) if symbol_display else None

        if not company and not normalized_symbol:
            continue

        if normalized_symbol:
            if normalized_symbol in seen_symbols:
                continue
            seen_symbols.add(normalized_symbol)
        else:
            normalized_company = company.lower()
            if normalized_company in seen_companies:
                continue
            seen_companies.add(normalized_company)

        cleaned_entities.append({
            "company": company,
            "symbol": symbol_display if symbol_display else "",
        })

    print(f"🏢 Extracted {len(cleaned_entities)} company entities")
    return cleaned_entities


def _select_reference_price(history_df, cutoff_date):
    if history_df.empty:
        return None

    subset = history_df.loc[history_df.index <= cutoff_date]
    if subset.empty:
        return None
    return float(subset['Close'].iloc[-1])


def _compute_symbol_momentum(symbol):
    ticker = clean_ticker_symbol(symbol)
    if not ticker:
        return None

    print(f"📈 Gathering momentum data for {ticker}")

    try:
        stock = yf.Ticker(ticker)
    except Exception as e:
        print(f"⚠️  Failed to initialize yfinance for {ticker}: {e}")
        return None

    history_daily = pd.DataFrame()
    try:
        history_daily = stock.history(period="1y", interval="1d", auto_adjust=False)
    except Exception as e:
        print(f"⚠️  Failed to fetch 1y daily history for {ticker}: {e}")

    if history_daily is None or history_daily.empty:
        print(f"⚠️  No 1y daily history available for {ticker}")
        return None

    intraday = pd.DataFrame()
    try:
        intraday = stock.history(period="1d", interval="1m", auto_adjust=False)
    except Exception as e:
        print(f"⚠️  Failed to fetch intraday history for {ticker}: {e}")

    latest_row = history_daily.iloc[-1]
    current_price = float(latest_row.get('Close'))
    previous_close = float(history_daily['Close'].iloc[-2]) if len(history_daily) > 1 else None
    daily_pct = _pct_change(current_price, previous_close)

    latest_date = history_daily.index[-1]
    yoy_reference_date = latest_date - pd.DateOffset(years=1)
    yoy_price = _select_reference_price(history_daily, yoy_reference_date)
    yoy_pct = _pct_change(current_price, yoy_price)

    mom_reference_date = latest_date - pd.DateOffset(months=1)
    mom_price = _select_reference_price(history_daily, mom_reference_date)
    mom_pct = _pct_change(current_price, mom_price)

    ten_min_pct = None
    if intraday is not None and not intraday.empty:
        latest_intraday_price = float(intraday['Close'].iloc[-1])
        ten_min_cutoff = intraday.index[-1] - pd.Timedelta(minutes=10)
        past_window = intraday.loc[intraday.index <= ten_min_cutoff]
        if not past_window.empty:
            price_10_min = float(past_window['Close'].iloc[-1])
            ten_min_pct = _pct_change(latest_intraday_price, price_10_min)
        current_price = latest_intraday_price  # Prefer real-time price when available

    day_high = float(latest_row.get('High')) if latest_row.get('High') is not None else None
    day_low = float(latest_row.get('Low')) if latest_row.get('Low') is not None else None
    volume = float(latest_row.get('Volume')) if latest_row.get('Volume') is not None else None

    last_year = history_daily.tail(252)
    high_52 = float(last_year['High'].max()) if not last_year.empty else None
    low_52 = float(last_year['Low'].min()) if not last_year.empty else None

    return {
        "symbol": ticker,
        "price": current_price,
        "daily_pct": daily_pct,
        "yoy_pct": yoy_pct,
        "mom_pct": mom_pct,
        "ten_min_pct": ten_min_pct,
        "volume": volume,
        "day_high": day_high,
        "day_low": day_low,
        "high_52": high_52,
        "low_52": low_52,
    }


def build_momentum_recap(entities):
    symbols_in_order = []
    company_names = {}
    for entry in entities:
        symbol = clean_ticker_symbol(entry.get('symbol')) if isinstance(entry, dict) else None
        if not symbol:
            continue
        if symbol not in symbols_in_order:
            symbols_in_order.append(symbol)
            company_names[symbol] = entry.get('company', '') if isinstance(entry, dict) else ''

    momentum_data = []
    for symbol in symbols_in_order:
        snapshot = _compute_symbol_momentum(symbol)
        if snapshot:
            snapshot['company'] = company_names.get(symbol, '')
            momentum_data.append(snapshot)

    if not momentum_data:
        return momentum_data, "- No momentum data available"

    lines = []
    for snapshot in momentum_data:
        name = snapshot.get('company') or snapshot['symbol']
        symbol = snapshot['symbol']
        price = snapshot.get('price')
        daily_pct = _format_percent(snapshot.get('daily_pct'))
        mom_pct = _format_percent(snapshot.get('mom_pct'))
        yoy_pct = _format_percent(snapshot.get('yoy_pct'))
        ten_pct = _format_percent(snapshot.get('ten_min_pct'))
        volume = _format_number(snapshot.get('volume'))
        day_range = (
            f"{snapshot['day_low']:.2f}-{snapshot['day_high']:.2f}"
            if snapshot.get('day_low') is not None and snapshot.get('day_high') is not None
            else "N/A"
        )
        range_52w = (
            f"{snapshot['low_52']:.2f}-{snapshot['high_52']:.2f}"
            if snapshot.get('low_52') is not None and snapshot.get('high_52') is not None
            else "N/A"
        )
        price_text = f"${price:.2f}" if price is not None else "N/A"

        lines.append(
            f"- {name} ({symbol}): Price {price_text} | Daily {daily_pct} | MoM {mom_pct} | YoY {yoy_pct} | "
            f"10m {ten_pct} | Vol {volume} | Day {day_range} | 52w {range_52w}"
        )

    return momentum_data, "\n".join(lines)

def execute_real_world_trade(decision):
    """
    Execute a real trade through Schwab API when in real_world mode.
    
    MULTI-LAYER SAFETY PROTECTION:
    1. DAI_SCHWAB_READONLY flag check (for testing)
    2. Trading mode check (must be 'real_world')
    3. Market hours check
    4. Safety manager validation
    """
    import os
    
    # SAFETY LAYER 1: Read-only mode check (for safe API testing)
    readonly_mode = os.environ.get('DAI_SCHWAB_READONLY', '0') == '1'
    if readonly_mode:
        print("🔒 SCHWAB READ-ONLY MODE ACTIVE")
        print("   ⛔ ALL TRADE EXECUTION DISABLED FOR SAFETY")
        print(f"   Decision would be: {decision.get('action', 'N/A').upper()} {decision.get('ticker', 'N/A')} ${decision.get('amount_usd', 0)}")
        print("   To enable trades: Remove DAI_SCHWAB_READONLY flag")
        return False
    
    # SAFETY LAYER 2: Trading mode check
    trading_mode = get_trading_mode()
    if trading_mode != "real_world":
        return True  # Skip real execution in simulation mode
    
    # SAFETY LAYER 3: Market hours check
    if not is_market_open():
        print(f"⛔ Cannot execute real trade - market is closed")
        return False
    
    try:
        # Import trading interface (only when needed)
        from trading_interface import trading_interface
        
        action = decision.get('action', '').lower()
        ticker = decision.get('ticker', '')
        amount_usd = decision.get('amount_usd', 0)
        
        # SAFETY LAYER 4: Action validation
        if action not in ['buy', 'sell']:
            return True  # Hold decisions don't require real execution
        
        print(f"💰 EXECUTING REAL TRADE via Schwab API:")
        print(f"   Action: {action.upper()}")
        print(f"   Ticker: {ticker}")
        print(f"   Amount: ${amount_usd}")
        
        if action == 'buy':
            result = trading_interface.execute_buy_order(ticker, amount_usd)
        elif action == 'sell':
            # For sell orders, we need to determine shares from holdings
            current_holdings = fetch_holdings()
            holding = next((h for h in current_holdings if h['ticker'] == ticker), None)
            if holding and holding['shares'] > 0:
                result = trading_interface.execute_sell_order(ticker, holding['shares'])
            else:
                print(f"⚠️  Cannot sell {ticker} - no shares found in holdings")
                return False

        if not result:
            print("❌ REAL TRADE FAILED: No response from trading interface")
            return False

        if result.get('success'):
            print(f"✅ REAL TRADE EXECUTED: {action.upper()} {ticker} for ${amount_usd}")
            print(f"   Order ID: {result.get('order_id', 'N/A')}")
            return True
        else:
            print(f"❌ REAL TRADE FAILED: {action.upper()} {ticker}")
            error_detail = result.get('error') or result.get('reason') or 'Unknown error'
            print(f"   Error: {error_detail}")
            order_status = result.get('order_status')
            if isinstance(order_status, dict):
                print(f"   Schwab Status: {order_status.get('status')} Reason: {order_status.get('reason')}")
            return False
            
    except ImportError:
        print("⚠️  Trading interface not available for real-world trading")
        print("🔄 Falling back to simulation mode for this trade")
        return True
    except Exception as e:
        print(f"❌ Real trade execution error: {e}")
        import traceback
        traceback.print_exc()
        return False

def update_holdings(decisions, skip_live_execution=False, run_id=None):
    # Use Pacific time as naive timestamp (database stores as-is, dashboard formats correctly)
    pacific_now = datetime.now(PACIFIC_TIMEZONE)
    timestamp = pacific_now.replace(tzinfo=None)  # Store as naive Pacific time
    skipped_decisions = []
    trading_mode = get_trading_mode()
    config_hash = get_current_config_hash()
    one_trade_mode = _os.getenv("DAI_ONE_TRADE_MODE", "0") == "1"
    allowed_buy_idx = None

    live_execution_enabled = trading_mode == "real_world" and not skip_live_execution

    latest_live_snapshot = {"data": None}

    def _sync_live_positions(stage):
        if not live_execution_enabled:
            return None
        try:
            from trading_interface import trading_interface
            print(f"🔄 Syncing Schwab positions ({stage})...")
            snapshot = trading_interface.sync_schwab_positions(persist=True)
            if snapshot and snapshot.get("status") == "success":
                latest_live_snapshot["data"] = snapshot
            return snapshot
        except Exception as exc:
            print(f"⚠️  Schwab sync ({stage}) failed: {exc}")
            return None

    def _latest_settled_snapshot():
        """Ensure we have the freshest Schwab snapshot before enforcing settled-funds guardrails."""
        if not live_execution_enabled:
            return None
        snapshot = latest_live_snapshot.get("data")
        if snapshot and snapshot.get("status") == "success":
            return snapshot
        return _sync_live_positions("settled-funds-check")

    def _current_cash_balance():
        with engine.begin() as _conn:
            cash_row_local = _conn.execute(text(
                "SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash"
            ), {"config_hash": config_hash}).fetchone()
            return float(cash_row_local.current_value) if cash_row_local else MAX_FUNDS

    if one_trade_mode:
        print("🎯 One-trade pilot mode active - enforcing single live buy limit")
        for idx, decision in enumerate(decisions):
            if (decision.get('action') or '').lower() == 'buy':
                allowed_buy_idx = idx
                break
        if allowed_buy_idx is None:
            print("⚠️  One-trade mode: no BUY decision provided; all live trades will be skipped")
    
    print(f"🔄 Updating holdings in {trading_mode.upper()} mode (config: {config_hash})")
    
    # CRITICAL: Check market hours BEFORE executing ANY trades
    if not is_market_open():
        eastern_now = pacific_now.astimezone(EASTERN_TIMEZONE)
        print(f"⛔ MARKET CLOSED - No trades will be executed")
        print(f"   Current time: {eastern_now.strftime('%I:%M %p %Z')}")
        print(f"   Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday")
        print(f"   Decisions recorded for review only")
        
        # Record decisions but don't execute
        print(f"📝 Recording {len(decisions)} decisions without execution:")
        for decision in decisions:
            action = decision.get('action', 'N/A')
            ticker = decision.get('ticker', 'N/A')
            print(f"   - {action.upper()} {ticker} (deferred until market open)")
        
        # DO NOT call process_sell_decisions or process_buy_decisions
        # Just return - decisions are already stored by store_trade_decisions()
        return
    
    # Market is open - proceed with execution
    print(f"✅ Market is OPEN - Proceeding with trade execution")
    
    if not live_execution_enabled:
        print("🎮 Running in simulation mode - no real trades executed")

    decisions_with_idx = []
    for idx, decision in enumerate(decisions):
        normalized = {
            **decision,
            "action": (decision.get("action") or "").lower(),
        }
        decisions_with_idx.append((idx, normalized))

    all_buy_decisions = [norm for idx, norm in decisions_with_idx if norm["action"] == "buy"]
    sell_decisions = [norm for idx, norm in decisions_with_idx if norm["action"] == "sell"]
    buy_decisions = list(all_buy_decisions)
    hold_decisions = [norm for idx, norm in decisions_with_idx if norm["action"] not in ("buy", "sell")]

    if one_trade_mode:
        if allowed_buy_idx is not None:
            buy_decisions = [
                norm for idx, norm in decisions_with_idx
                if idx == allowed_buy_idx and norm["action"] == "buy"
            ]
        else:
            buy_decisions = []

        skipped_extra_buys = 0
        for idx, norm in decisions_with_idx:
            if norm["action"] == "buy" and (allowed_buy_idx is None or idx != allowed_buy_idx):
                skipped_extra_buys += 1
                skipped_decisions.append({
                    **norm,
                    "reason": "One-trade pilot mode - additional buy skipped",
                })
        if skipped_extra_buys:
            print(f"⏭️  One-trade mode skipped {skipped_extra_buys} additional buy decision(s)")

        if sell_decisions:
            print(f"⏭️  One-trade mode skipping {len(sell_decisions)} sell decision(s)")
            for norm in sell_decisions:
                skipped_decisions.append({
                    **norm,
                    "reason": "One-trade pilot mode - sell execution disabled",
                })
            sell_decisions = []
    elif live_execution_enabled:
        if len(sell_decisions) > 2:
            overflow = sell_decisions[2:]
            sell_decisions = sell_decisions[:2]
            for norm in overflow:
                skipped_decisions.append({
                    **norm,
                    "reason": "Live mode limit reached - max 2 sells executed",
                })
            print(f"⏭️  Live mode capped additional {len(overflow)} sell decision(s)")
        if len(buy_decisions) > 2:
            overflow = buy_decisions[2:]
            buy_decisions = buy_decisions[:2]
            for norm in overflow:
                skipped_decisions.append({
                    **norm,
                    "reason": "Live mode limit reached - max 2 buys executed",
                })
            print(f"⏭️  Live mode capped additional {len(overflow)} buy decision(s)")

    print(f"📊 Processing {len(sell_decisions)} sells, {len(buy_decisions)} buys, {len(hold_decisions)} holds")
    
    # Get current cash balance
    with engine.begin() as conn:
        cash_row = conn.execute(text("SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash}).fetchone()
        available_cash = float(cash_row.current_value) if cash_row else MAX_FUNDS
        print(f"💰 Starting cash balance: ${available_cash:.2f}")

    # 1) EXECUTE ALL SELLS FIRST (to free up cash)
    if sell_decisions:
        print(f"🔥 Executing {len(sell_decisions)} sell orders first...")
        available_cash = process_sell_decisions(
            sell_decisions,
            available_cash,
            timestamp,
            config_hash,
            skipped_decisions,
            live_execution_enabled,
        )
        _sync_live_positions("post-sell")
        available_cash = _current_cash_balance()
        print(f"💰 Cash after sells: ${available_cash:.2f}")

    # Wait 30 seconds between sells and buys if both exist (allows position swapping)
    if sell_decisions and buy_decisions:
        print("⏳ Waiting 30 seconds after sells to allow funds to clear before buys...")
        import time
        time.sleep(30)
        _sync_live_positions("post-wait")
        available_cash = _current_cash_balance()
        print(f"💰 Cash after wait: ${available_cash:.2f}")

    # Enforce settled-funds guardrail for cash accounts before any buys
    if live_execution_enabled and not IS_MARGIN_ACCOUNT:
        snapshot = _latest_settled_snapshot()
        if snapshot and snapshot.get("status") == "success":
            raw_settled = float(
                snapshot.get("cash_balance")
                or snapshot.get("cash_balance_settled")
                or snapshot.get("settled_cash_strict")
                or 0.0
            )
            unsettled_cash = float(snapshot.get("unsettled_cash") or 0.0)
            settled_limit = max(raw_settled - unsettled_cash, 0.0)
            print(
                f"🔒 Settled funds check: raw_settled=${raw_settled:.2f}, unsettled=${unsettled_cash:.2f}, usable=${settled_limit:.2f}"
            )
            adjusted_cash = min(available_cash, settled_limit)
            if settled_limit <= 0:
                if buy_decisions:
                    print("⚠️  Settled cash is $0. Skipping live buys to avoid good-faith violations.")
                    guardrail_reason = "Trade blocked: no settled funds available (good-faith guardrail)."
                    for dec in buy_decisions:
                        skipped_decisions.append({**dec, "reason": guardrail_reason})
                buy_decisions = []
            else:
                if abs(adjusted_cash - available_cash) > 1e-6:
                    print(
                        f"🔒 Settled-funds guardrail in effect: ${available_cash:.2f} → ${adjusted_cash:.2f} usable."
                    )
                available_cash = adjusted_cash
        else:
            retry_snapshot = _sync_live_positions("settled-funds-retry")
            if retry_snapshot and retry_snapshot.get("status") == "success":
                snapshot = retry_snapshot
                raw_settled = float(
                    snapshot.get("cash_balance")
                    or snapshot.get("cash_balance_settled")
                    or snapshot.get("settled_cash_strict")
                    or 0.0
                )
                unsettled_cash = float(snapshot.get("unsettled_cash") or 0.0)
                settled_limit = max(raw_settled - unsettled_cash, 0.0)
                print(
                    f"🔄 Settled funds retry succeeded: raw_settled=${raw_settled:.2f}, unsettled=${unsettled_cash:.2f}, usable=${settled_limit:.2f}"
                )
                adjusted_cash = min(available_cash, settled_limit)
                if settled_limit <= 0:
                    if buy_decisions:
                        print("⚠️  Settled cash is $0 after retry. Skipping live buys to avoid good-faith violations.")
                        guardrail_reason = "Trade blocked: no settled funds available (good-faith guardrail)."
                        for dec in buy_decisions:
                            skipped_decisions.append({**dec, "reason": guardrail_reason})
                    buy_decisions = []
                else:
                    if abs(adjusted_cash - available_cash) > 1e-6:
                        print(
                            f"🔒 Settled-funds guardrail (retry) in effect: ${available_cash:.2f} → ${adjusted_cash:.2f} usable."
                        )
                    available_cash = adjusted_cash
            else:
                if buy_decisions:
                    print("⚠️  Unable to verify settled funds; skipping live buys to avoid good-faith violations.")
                    guardrail_reason = "Trade blocked: unable to verify settled-fund balance (good-faith guardrail)."
                    for dec in buy_decisions:
                        skipped_decisions.append({**dec, "reason": guardrail_reason})
                buy_decisions = []

    # 2) EXECUTE BUYS IN ORDER UNTIL CASH RUNS OUT  
    if buy_decisions:
        print(f"💸 Executing buy orders with ${available_cash:.2f} available...")
        available_cash = process_buy_decisions(
            buy_decisions,
            available_cash,
            timestamp,
            config_hash,
            skipped_decisions,
            live_execution_enabled,
        )
    
    # 3) Log hold decisions
    if hold_decisions:
        print(f"⏸️  {len(hold_decisions)} hold decisions (no action needed)")
        for decision in hold_decisions:
            skipped_decisions.append({
                **decision,
                "reason": f"Hold decision - no action taken (Original: {decision.get('reason', '')})"
            })

    _sync_live_positions("final")

    return skipped_decisions

def process_sell_decisions(sell_decisions, available_cash, timestamp, config_hash, skipped_decisions, live_execution_enabled):
    """Process all sell decisions and return updated cash balance"""
    
    # Track the cash we're adding from sells
    cash_from_sells = 0.0

    price_fetcher.prefetch_prices([clean_ticker_symbol(d.get("ticker")) for d in sell_decisions])
    
    with engine.begin() as conn:
        for decision in sell_decisions:
            ticker = decision.get("ticker")
            amount = float(decision.get("amount_usd", 0))
            reason = decision.get("reason", "")

            clean_ticker = clean_ticker_symbol(ticker)
            if not clean_ticker:
                print(f"❌ Skipping sell for {ticker} - invalid ticker symbol")
                skipped_decisions.append({**decision, "reason": f"Invalid ticker - {reason}"})
                continue

            # Get price first - we always want current/close price for analysis
            price = get_current_price(ticker)
            if not price:
                print(f"Skipping sell for {ticker} due to missing price (API rate limited).")
                skipped_decisions.append({
                    "action": "sell",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Price data unavailable due to API rate limiting (Original: {reason})"
                })
                continue

            if not is_market_open():
                print(f"⛔ Market closed - recording sell decision for {ticker} but NO execution.")
                skipped_decisions.append({
                    "action": "sell",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"⛔ MARKET CLOSED - No action taken. AI suggested sell at ${price:.2f}. Original: {reason}"
                })
                continue

            holding = conn.execute(
                text("SELECT shares, purchase_price, purchase_timestamp, reason FROM holdings WHERE ticker = :ticker AND config_hash = :config_hash AND is_active = TRUE AND shares > 0"),
                {"ticker": clean_ticker, "config_hash": config_hash}
            ).fetchone()
            if holding:
                if live_execution_enabled:
                    live_success = execute_real_world_trade(decision)
                    if not live_success:
                        print(f"⚠️  Real sell execution failed for {ticker}, continuing with simulation bookkeeping")

                shares = float(holding.shares)
                purchase_price = float(holding.purchase_price)
                total_value = shares * price
                purchase_value = shares * purchase_price
                gain_loss = total_value - purchase_value

                holding_data = {
                    'purchase_price': purchase_price,
                    'shares': shares,
                    'purchase_timestamp': holding.purchase_timestamp,
                    'reason': holding.reason
                }
                try:
                    outcome_category = feedback_tracker.record_sell_outcome(
                        ticker, price, holding_data, reason
                    )
                    print(f"Sell outcome recorded for {ticker}: {outcome_category}")
                except Exception as e:
                    print(f"Failed to record sell outcome for {ticker}: {e}")

                conn.execute(text("""
                        UPDATE holdings SET
                            shares = 0,
                            is_active = FALSE,
                            current_price = :price,
                            current_price_timestamp = :timestamp,
                            current_value = :value,
                            gain_loss = :gain_loss
                        WHERE ticker = :ticker AND config_hash = :config_hash
                    """), {
                        "ticker": clean_ticker,
                        "price": float(price),
                        "timestamp": timestamp,
                        "value": total_value,
                        "gain_loss": gain_loss,
                        "config_hash": config_hash
                    })

                cash_from_sells += total_value
                print(f"💰 Sold {ticker}: {shares} shares at ${price:.2f} = ${total_value:.2f} (Gain/Loss: ${gain_loss:.2f})")

            else:
                # Check if it's inactive or just doesn't exist
                inactive_check = conn.execute(
                    text("SELECT shares, is_active FROM holdings WHERE ticker = :ticker AND config_hash = :config_hash"),
                    {"ticker": clean_ticker, "config_hash": config_hash}
                ).fetchone()
                
                if inactive_check:
                    if not inactive_check.is_active:
                        print(f"⚠️  {ticker} is already INACTIVE (previously sold) - skipping duplicate sell")
                        reason_msg = f"Already sold - position is inactive (Original: {reason})"
                    else:
                        print(f"⚠️  {ticker} has 0 shares - nothing to sell")
                        reason_msg = f"No shares to sell (Original: {reason})"
                else:
                    print(f"❌ No holding found for {ticker} (cleaned: {clean_ticker}) - cannot sell")
                    reason_msg = f"No holding found to sell (Original: {reason})"
                
                skipped_decisions.append({
                    "action": "sell",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": reason_msg
                })

        # Update cash balance after all sells are processed
        if cash_from_sells > 0:
            # Get current cash balance and add the proceeds from sells
            cash_result = conn.execute(text("""
                SELECT current_value FROM holdings 
                WHERE ticker = 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash}).fetchone()
            
            current_cash = float(cash_result.current_value) if cash_result else 0.0
            new_cash_balance = current_cash + cash_from_sells
            
            conn.execute(text("""
                UPDATE holdings SET
                    current_price = :cash,
                    current_value = :cash,
                    total_value = :cash,
                    current_price_timestamp = :timestamp
                WHERE ticker = 'CASH' AND config_hash = :config_hash
            """), {"cash": new_cash_balance, "timestamp": timestamp, "config_hash": config_hash})
            print(f"💰 Cash updated: ${current_cash:.2f} + ${cash_from_sells:.2f} = ${new_cash_balance:.2f}")
            
            return new_cash_balance
        else:
            return available_cash

def process_buy_decisions(buy_decisions, available_cash, timestamp, config_hash, skipped_decisions, live_execution_enabled):
    if buy_decisions:
        price_fetcher.prefetch_prices([clean_ticker_symbol(d.get("ticker")) for d in buy_decisions])
        with engine.begin() as conn:
            cash_row = conn.execute(text("SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash})\
                .fetchone()
            cash = float(cash_row.current_value) if cash_row else MAX_FUNDS

            for decision in buy_decisions:
                ticker = decision.get("ticker")
                amount = float(decision.get("amount_usd", 0))
                reason = decision.get("reason", "")

                clean_ticker = clean_ticker_symbol(ticker)
                if not clean_ticker:
                    print(f"Skipping buy for {ticker} due to invalid ticker symbol.")
                    continue

                if not is_market_open():
                    print(f"⛔ Skipping buy for {ticker} - market is closed.")
                    skipped_decisions.append({
                        "action": "buy",
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"⛔ MARKET CLOSED - No action taken. AI suggested buy. Original: {reason}"
                    })
                    continue

                price = get_current_price(ticker)
                if not price:
                    print(f"Skipping buy for {ticker} due to missing price.")
                    skipped_decisions.append({
                        "action": "buy",
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Price data unavailable - no trade executed (Original: {reason})"
                    })
                    continue

                shares = floor(amount / price)
                if shares == 0:
                    print(f"Skipping buy for {ticker} due to insufficient funds for 1 share.")
                    skipped_decisions.append({
                        "action": "buy",
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Insufficient funds for 1 share - no trade executed (Original: {reason})"
                    })
                    continue

                actual_spent = shares * price
                if cash - actual_spent < MIN_BUFFER:
                    print(f"Skipping buy for {ticker}, would breach minimum buffer.")
                    skipped_decisions.append({
                        "action": "buy",
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Would breach minimum buffer - no trade executed (Original: {reason})"
                    })
                    continue

                existing = conn.execute(
                    text("SELECT shares, total_value, gain_loss, is_active, reason FROM holdings WHERE ticker = :ticker AND config_hash = :config_hash"),
                    {"ticker": clean_ticker, "config_hash": config_hash}
                ).fetchone()

                if existing and existing.is_active:
                    new_shares = float(existing.shares) + shares
                    new_total_value = float(existing.total_value) + actual_spent
                    new_current_value = new_shares * price
                    new_gain_loss = new_current_value - new_total_value
                    new_avg_price = new_total_value / new_shares

                    conn.execute(text("""
                        UPDATE holdings SET
                            shares = :shares,
                            purchase_price = :avg_price,
                            current_price = :current_price,
                            purchase_timestamp = :timestamp,
                            current_price_timestamp = :timestamp,
                            total_value = :total_value,
                            current_value = :current_value,
                            gain_loss = :gain_loss,
                            reason = :reason
                        WHERE ticker = :ticker AND config_hash = :config_hash
                    """), {
                        "ticker": clean_ticker,
                        "shares": new_shares,
                        "avg_price": new_avg_price,
                        "current_price": float(price),
                        "timestamp": timestamp,
                        "total_value": new_total_value,
                        "current_value": new_current_value,
                        "gain_loss": new_gain_loss,
                        "reason": f"{existing.reason if existing.reason else ''} + {reason}",
                        "config_hash": config_hash
                    })
                    print(f"Added {shares} shares of {clean_ticker}. Total: {new_shares} shares, Avg cost: ${new_avg_price:.2f}")
                elif existing and not existing.is_active:
                    conn.execute(text("""
                        UPDATE holdings SET
                            shares = :shares,
                            purchase_price = :purchase_price,
                            current_price = :current_price,
                            purchase_timestamp = :timestamp,
                            current_price_timestamp = :timestamp,
                            total_value = :total_value,
                            current_value = :current_value,
                            gain_loss = :gain_loss,
                            reason = :reason,
                            is_active = TRUE
                        WHERE ticker = :ticker AND config_hash = :config_hash
                    """), {
                        "ticker": clean_ticker,
                        "shares": float(shares),
                        "purchase_price": float(price),
                        "current_price": float(price),
                        "timestamp": timestamp,
                        "total_value": float(shares * price),
                        "current_value": float(shares * price),
                        "gain_loss": 0.0,
                        "reason": reason,
                        "config_hash": config_hash
                    })
                    print(f"Reactivated {clean_ticker}: {shares} shares at ${price:.2f}")
                else:
                    conn.execute(text("""
                        INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                        VALUES (:config_hash, :ticker, :shares, :purchase_price, :current_price, :purchase_timestamp, :current_price_timestamp, :total_value, :current_value, :gain_loss, :reason, TRUE)
                    """), {
                        "config_hash": config_hash,
                        "ticker": clean_ticker,
                        "shares": float(shares),
                        "purchase_price": float(price),
                        "current_price": float(price),
                        "purchase_timestamp": timestamp,
                        "current_price_timestamp": timestamp,
                        "total_value": float(shares * price),
                        "current_value": float(shares * price),
                        "gain_loss": 0.0,
                        "reason": reason
                    })
                    print(f"First purchase: {shares} shares of {clean_ticker} at ${price:.2f}")

                cash -= actual_spent

            # Persist updated cash after buys
            conn.execute(text("""
                UPDATE holdings SET
                    current_price = :cash,
                    current_value = :cash,
                    total_value = :cash,
                    current_price_timestamp = :timestamp
                WHERE ticker = 'CASH' AND config_hash = :config_hash
            """), {"cash": cash, "timestamp": timestamp, "config_hash": config_hash})

    # 3) Handle HOLD records for visibility
    for decision in hold_decisions:
        ticker = decision.get("ticker")
        reason = decision.get("reason", "")
        print(f"Holding {ticker} - no action taken")
        skipped_decisions.append({
            "action": "hold",
            "ticker": ticker,
            "amount_usd": 0,
            "reason": f"Hold decision: {reason}"
        })

    if skipped_decisions:
        # Use provided run_id when available for easier traceability
        skip_run_id = run_id
        if not skip_run_id:
            pacific_now = datetime.now(PACIFIC_TIMEZONE)
            skip_run_id = pacific_now.strftime("%Y%m%dT%H%M%S")
        store_trade_decisions(skipped_decisions, f"{skip_run_id}_skipped")
        print(f"Stored {len(skipped_decisions)} skipped decisions due to price/data issues")

def process_buy_decisions(buy_decisions, available_cash, timestamp, config_hash, skipped_decisions, live_execution_enabled):
    """Process all buy decisions and return updated cash balance"""
    
    price_fetcher.prefetch_prices([clean_ticker_symbol(d.get("ticker")) for d in buy_decisions])

    with engine.begin() as conn:
        for decision in buy_decisions:
            ticker = decision.get("ticker")
            amount = float(decision.get("amount_usd", 0))
            reason = decision.get("reason", "")

            clean_ticker = clean_ticker_symbol(ticker)
            if not clean_ticker:
                print(f"Skipping buy for {ticker} due to invalid ticker symbol.")
                skipped_decisions.append({**decision, "reason": f"Invalid ticker - {reason}"})
                continue

            # Get price first - we always want current/close price for analysis
            price = get_current_price(ticker)
            if not price:
                print(f"Skipping buy for {ticker} due to missing price (API rate limited).")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Price data unavailable due to API rate limiting (Original: {reason})"
                })
                continue

            if not is_market_open():
                print(f"⛔ Market closed - recording buy decision for {ticker} but NO execution.")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"⛔ MARKET CLOSED - No action taken. AI suggested buy at ${price:.2f}. Original: {reason}"
                })
                continue

            from math import floor
            requested_shares = floor(amount / price)
            if requested_shares == 0:
                print(f"Skipping buy for {ticker} due to insufficient funds for 1 share (need ${price:.2f}, have ${amount:.2f}).")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Insufficient funds for 1 share (need ${price:.2f}, allocated ${amount:.2f}) - no trade executed (Original: {reason})"
                })
                continue

            buffer_safe_cash = max(available_cash - MIN_BUFFER, 0.0)
            max_affordable_shares = floor(buffer_safe_cash / price) if price > 0 else 0
            if max_affordable_shares <= 0:
                print(
                    f"Skipping buy for {ticker} - settled funds limit allows $0 beyond buffer "
                    f"(available ${available_cash:.2f}, buffer ${MIN_BUFFER:.2f})."
                )
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Settled funds limit left no usable cash (Original: {reason})"
                })
                continue

            shares = min(requested_shares, max_affordable_shares)
            if shares <= 0:
                print(f"Skipping buy for {ticker} - cannot allocate shares without breaching settled-funds guardrail.")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Settled-funds guardrail prevented purchase (Original: {reason})"
                })
                continue

            actual_spent = round(shares * price, 2)
            if shares < requested_shares:
                requested_value = round(requested_shares * price, 2)
                print(
                    f"✂️ Adjusted buy for {ticker}: requested {requested_shares} shares (~${requested_value:.2f}), "
                    f"buying {shares} share(s) for ~${actual_spent:.2f} to stay within settled funds (${available_cash:.2f} available)."
                )

            if available_cash - actual_spent < MIN_BUFFER - 1e-6:
                print(f"Skipping buy for {ticker} - would exceed budget even after adjustment (need ${actual_spent:.2f}, available ${available_cash:.2f})")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Budget exceeded after guardrail adjustment - no trade executed (Original: {reason})"
                })
                continue

            decision.setdefault("amount_usd_requested", amount)
            decision["amount_usd"] = actual_spent
            decision["amount_usd_executed"] = actual_spent

            # Execute real-world trade if enabled
            if live_execution_enabled:
                real_trade_success = execute_real_world_trade(decision)
                if not real_trade_success:
                    print(f"⚠️  Real buy execution failed for {ticker}, recording in simulation only")

            # Execute the buy in simulation (always) 
            try:
                existing = conn.execute(
                    text("SELECT shares, purchase_price, total_value, current_value, gain_loss, is_active, reason FROM holdings WHERE ticker = :ticker AND config_hash = :config_hash"),
                    {"ticker": clean_ticker, "config_hash": config_hash}
                ).fetchone()

                if existing and existing.is_active:
                    # Average cost basis calculation
                    existing_shares = float(existing.shares)
                    existing_avg_price = float(existing.purchase_price)
                    existing_total_value = float(existing.total_value)

                    new_shares = existing_shares + shares
                    new_total_value = existing_total_value + actual_spent
                    new_avg_price = new_total_value / new_shares
                    new_current_value = new_shares * price
                    new_gain_loss = new_current_value - new_total_value

                    conn.execute(text("""
                        UPDATE holdings SET
                            shares = :shares,
                            purchase_price = :avg_price,
                            current_price = :current_price,
                            purchase_timestamp = :timestamp,
                            current_price_timestamp = :timestamp,
                            total_value = :total_value,
                            current_value = :current_value,
                            gain_loss = :gain_loss,
                            reason = :reason
                        WHERE ticker = :ticker AND config_hash = :config_hash
                    """), {
                        "ticker": clean_ticker,
                        "shares": new_shares,
                        "avg_price": new_avg_price,
                        "current_price": float(price),
                        "timestamp": timestamp,
                        "total_value": new_total_value,
                        "current_value": new_current_value,
                        "gain_loss": new_gain_loss,
                        "reason": f"{existing.reason if existing.reason else ''} + {reason}",
                        "config_hash": config_hash
                    })
                    print(f"Added {shares} shares of {clean_ticker}. Total: {new_shares} shares, Avg cost: ${new_avg_price:.2f}")
                elif existing and not existing.is_active:
                    conn.execute(text("""
                        UPDATE holdings SET
                            shares = :shares,
                            purchase_price = :purchase_price,
                            current_price = :current_price,
                            purchase_timestamp = :timestamp,
                            current_price_timestamp = :timestamp,
                            total_value = :total_value,
                            current_value = :current_value,
                            gain_loss = :gain_loss,
                            reason = :reason,
                            is_active = TRUE
                        WHERE ticker = :ticker AND config_hash = :config_hash
                    """), {
                        "ticker": clean_ticker,
                        "shares": shares,
                        "purchase_price": float(price),
                        "current_price": float(price),
                        "timestamp": timestamp,
                        "total_value": actual_spent,
                        "current_value": shares * price,
                        "gain_loss": 0.0,
                        "reason": reason,
                        "config_hash": config_hash
                    })
                    print(f"Reactivated {clean_ticker} with {shares} shares at ${price:.2f}")
                else:
                    conn.execute(text("""
                        INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, 
                                            purchase_timestamp, current_price_timestamp, total_value, 
                                            current_value, gain_loss, reason, is_active)
                        VALUES (:config_hash, :ticker, :shares, :purchase_price, :current_price, 
                                :timestamp, :timestamp, :total_value, :current_value, :gain_loss, :reason, TRUE)
                    """), {
                        "config_hash": config_hash,
                        "ticker": clean_ticker,
                        "shares": shares,
                        "purchase_price": float(price),
                        "current_price": float(price),
                        "timestamp": timestamp,
                        "total_value": actual_spent,
                        "current_value": shares * price,
                        "gain_loss": 0.0,
                        "reason": reason
                    })
                    print(f"Bought {shares} shares of {clean_ticker} at ${price:.2f} for ${actual_spent:.2f}")

                # Update cash balance
                available_cash -= actual_spent
                conn.execute(text("""
                    UPDATE holdings SET
                        current_price = :cash,
                        current_value = :cash,
                        total_value = :cash,
                        current_price_timestamp = :timestamp
                    WHERE ticker = 'CASH' AND config_hash = :config_hash
                """), {"cash": available_cash, "timestamp": timestamp, "config_hash": config_hash})

            except Exception as e:
                print(f"❌ Error executing buy for {ticker}: {e}")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Execution error: {e} (Original: {reason})"
                })
                continue

    return available_cash

def record_portfolio_snapshot():
    """Record current portfolio state for historical tracking - same as dashboard_server"""
    with engine.begin() as conn:
        # Ensure portfolio_history table exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id SERIAL PRIMARY KEY,
                config_hash VARCHAR(50) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_portfolio_value FLOAT,
                cash_balance FLOAT,
                total_invested FLOAT,
                total_profit_loss FLOAT,
                percentage_gain FLOAT,
                holdings_snapshot JSONB
            )
        """))
        
        # Get current holdings
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, 
                   total_value, current_value, gain_loss
            FROM holdings
            WHERE is_active = TRUE
        """)).fetchall()
        
        holdings = [dict(row._mapping) for row in result]
        
        # Calculate portfolio metrics
        cash_balance = next((h["current_value"] for h in holdings if h["ticker"] == "CASH"), 0)
        stock_holdings = [h for h in holdings if h["ticker"] != "CASH"]
        
        total_current_value = sum(h["current_value"] for h in stock_holdings)
        total_invested = sum(h["total_value"] for h in stock_holdings)
        total_profit_loss = sum(h["gain_loss"] for h in stock_holdings)
        total_portfolio_value = total_current_value + cash_balance
        
        percentage_gain = (total_profit_loss / total_invested * 100) if total_invested > 0 else 0
        
        # Record snapshot
        conn.execute(text("""
            INSERT INTO portfolio_history 
            (total_portfolio_value, cash_balance, total_invested, 
             total_profit_loss, percentage_gain, holdings_snapshot)
            VALUES (:total_portfolio_value, :cash_balance, :total_invested, 
                    :total_profit_loss, :percentage_gain, :holdings_snapshot)
        """), {
            "total_portfolio_value": total_portfolio_value,
            "cash_balance": cash_balance,
            "total_invested": total_invested,
            "total_profit_loss": total_profit_loss,
            "percentage_gain": percentage_gain,
            "holdings_snapshot": json.dumps(holdings)
        })

def ask_decision_agent(summaries, run_id, holdings):
    config_hash = get_current_config_hash()
    market_open = is_market_open()
    print(f"⏰ Market status at decision time: {'OPEN' if market_open else 'CLOSED'}")
    # Limit summaries to the targeted run_id when provided
    if run_id:
        run_scoped = [s for s in summaries if s.get('run_id') == run_id]
        if run_scoped:
            summaries = run_scoped
        else:
            print(f"⚠️  No summaries matched run_id {run_id}; proceeding with provided list of {len(summaries)} items")
        # config_hash already pulled for downstream usage; no change needed

# Get versioned prompt for DeciderAgent
    from prompt_manager import get_active_prompt
    try:
        prompt_data = get_active_prompt("DeciderAgent")
        system_prompt = prompt_data["system_prompt"]
        user_prompt_template = prompt_data["user_prompt_template"]
        prompt_version = prompt_data["version"]
        print(f"🔧 Using DeciderAgent prompt v{prompt_version} (UNIFIED)")
        
        # CRITICAL: Ensure ALL prompts end with proper JSON format requirements
        if "JSON" not in user_prompt_template.upper():
            print(f"⚠️  Prompt v{prompt_version} missing JSON formatting - adding required JSON template")
            user_prompt_template += """

🚨 CRITICAL TRADING INSTRUCTIONS:

1. FIRST: Review each existing position and decide whether to SELL, providing explicit reasoning
2. SECOND: Consider new BUY opportunities based on news analysis
3. Think in DOLLAR amounts, not share counts - the system will calculate shares

For each EXISTING holding, you MUST provide a sell decision or explicit reasoning why you're keeping it.

🚨 CRITICAL: You must respond ONLY with valid JSON in this exact format:
[
  {{
    "action": "sell" or "buy" or "hold",
    "ticker": "SYMBOL", 
    "amount_usd": dollar_amount_number,
    "reason": "detailed explanation including sell analysis for existing positions"
  }}
]

IMPORTANT:
- For SELL: amount_usd = 0 (we sell all shares)
- For BUY: amount_usd = dollars to invest (think $500, $1000, $2000 etc.)
- For HOLD: amount_usd = 0, but provide detailed reasoning why not selling

No explanatory text, no markdown, just pure JSON array."""
        
    except Exception as e:
        print(f"⚠️  Could not load versioned prompt: {e}, using fallback")
        # Fallback minimal prompt when versioned template is unavailable
        system_prompt = """You are a selective intraday trading AI. Focus on 1–2 day tactical opportunities, keep trades limited by daily caps, and output a JSON object with a `decisions` array."""

        user_prompt_template = """ACCOUNT
- Mode: {account_mode}
- Settled Funds (USD): ${settled_cash}

DAILY STATE
- Today tickets used / cap: {today_tickets_used}/{daily_ticket_cap}
- Today buys used / cap: {today_buys_used}/{daily_buy_cap}
- Minutes since last new entry: {minutes_since_last_entry}
- Tickers entered today: {tickers_entered_today}

INPUT SNAPSHOT
- Holdings: {holdings}
- Momentum Recap: {momentum_recap}
- Summaries: {summaries}
- Feedback: {feedback_context}

OUTPUT (STRICT)
{{"decisions":[{{"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"≤140 chars; momentum + catalyst; add visual cue if relevant; buys prefixed R1..Rk"}},...]}}"""

    contrarian_directive = """
🚫 CROWD-FADE DIRECTIVE
- Treat your first instinct as the herd move. Execute the smarter opposite: sell strength chased by headlines, buy panic where catalysts are overblown, and fade media-manufactured hype.
- NEVER chase names near 52-week highs or obvious “record high” banners. Assume mainstream news is manipulating retail entries; we make money by positioning against that narrative.
- Before finalizing each decision, ask: “What is the average sucker doing right now?” Then plan the inverse. If instinct says BUY, only proceed when you can justify why most traders are wrong—and mention it explicitly (“fade ATH chase”, “short squeeze exhaustion”, etc.).
- Document which crowd behavior you are exploiting in every reason (e.g., “Contrarian SELL into euphoric breakout”, “Contrarian BUY after panic dump”)."""
    if "CROWD-FADE DIRECTIVE" not in user_prompt_template:
        user_prompt_template = user_prompt_template.rstrip() + "\n\n" + contrarian_directive.strip()

    cash_horizon_block = """
⏳ CASH ACCOUNT PLAYBOOK (1–5 TRADING DAYS)
- This is a non-margin cash run; every BUY/SELL should assume a 1–5 session holding window, not a same-day scalp.
- Default to HOLD unless the trade thesis or catalyst broke, price hit your stop, or a clearly superior setup needs the slot. Small mark-to-market noise is not a sell reason.
- Treat the holdings block as the ground-truth P&L (purchase price, current price, gain/loss). Quote those numbers accurately; never describe a loss as a gain."""
    if not IS_MARGIN_ACCOUNT and "⏳ CASH ACCOUNT PLAYBOOK" not in user_prompt_template:
        user_prompt_template = user_prompt_template.rstrip() + "\n\n" + cash_horizon_block.strip()

    # Limit the number of summaries to process to avoid rate limiting
    # Process only the most recent summaries
    max_summaries = 10
    if len(summaries) > max_summaries:
        summaries = summaries[-max_summaries:]  # Take the most recent ones
        print(f"Processing only the {max_summaries} most recent summaries to avoid rate limiting")
    
    parsed_summaries = []
    for s in summaries:
        try:
            # The data is already stored as a JSON string in the database
            # We need to parse it to get the actual summary content
            if isinstance(s['data'], str):
                parsed = json.loads(s['data'])
            else:
                parsed = s['data']

            # Extract the summary from the parsed data
            summary_content = parsed.get('summary', {})
            if isinstance(summary_content, str):
                # If summary is a string, try to parse it as JSON
                try:
                    summary_content = json.loads(summary_content)
                except Exception:
                    # If it's not JSON, treat it as plain text
                    summary_content = {'headlines': [], 'insights': summary_content}

            # Truncate long insights to reduce token usage
            insights = summary_content.get('insights', '')
            if len(insights) > SUMMARY_MAX_CHARS:
                insights = insights[:SUMMARY_MAX_CHARS] + "... [truncated]"

            # Limit headlines to reduce token usage
            headlines = summary_content.get('headlines', [])
            if len(headlines) > 5:  # Limit to 5 headlines
                headlines = headlines[:5]

            parsed_summaries.append({
                "agent": s['agent'],
                "headlines": headlines,
                "insights": insights
            })
        except Exception as e:
            print(f"Failed to parse summary for agent {s['agent']}: {e}")
            # Add a fallback entry with basic info
            parsed_summaries.append({
                "agent": s['agent'],
                "headlines": [],
                "insights": f"Error parsing summary: {e}"
            })

    # Create a more concise summary text
    parsed_summaries.sort(key=lambda x: (x.get('agent') or '').lower())

    summary_parts = []
    extractor_blocks = []
    for s in parsed_summaries:
        agent_label = (s.get('agent') or 'unknown').strip().lower()
        headlines_text = ', '.join(s['headlines'][:3])  # Limit to 3 headlines per agent
        insights_text = s['insights'] if len(s['insights']) <= SUMMARY_MAX_CHARS else s['insights'][:SUMMARY_MAX_CHARS] + "... [truncated]"
        summary_parts.append(f"{agent_label}: {headlines_text} | {insights_text}")
        extractor_blocks.append(
            f"Agent: {agent_label}\nHeadlines: {headlines_text or 'None'}\nInsights: {insights_text or 'None'}"
        )

    summarized_text = "\n".join(summary_parts)
    summaries_for_extraction = "\n\n".join(extractor_blocks) if extractor_blocks else summarized_text
    print(f"📰 Summaries forwarded to Decider: {len(parsed_summaries)}")
    summary_preview_limit = int(os.getenv("DAI_SUMMARY_PREVIEW_LIMIT", "6000"))
    summary_snippet = summarized_text[:summary_preview_limit]
    print(f"🧾 Summaries preview (showing {len(summary_snippet)} of {len(summarized_text)} chars):\n{summary_snippet}")
    if len(summary_snippet) < len(summarized_text):
        print("… (summaries truncated for console preview)")

    company_entities = extract_companies_from_summaries(summaries_for_extraction)
    momentum_data, momentum_summary = build_momentum_recap(company_entities)
    print(f"📊 Momentum recap prepared for {len(momentum_data)} symbols")
    if momentum_summary:
        preview_text = momentum_summary[:6000]
        if len(momentum_summary) > 6000:
            preview_text += "... [truncated]"
        print("🧾 Momentum summary preview:\n" + preview_text)
    if momentum_data:
        sample = momentum_data[:3]
        print(f"🧪 Momentum data sample: {json.dumps(sample, default=str)[:500]}")
    momentum_recap = momentum_summary or "Momentum snapshot unavailable. Run the decider to refresh momentum data."
    try:
        store_momentum_snapshot(config_hash, run_id, company_entities, momentum_data, momentum_summary, momentum_recap)
    except Exception as persist_err:
        print(f"⚠️  Failed to persist momentum snapshot: {persist_err}")

    # Pull latest decider feedback context for prompt enrichment
    feedback_context = "No recent performance feedback recorded."
    try:
        latest_feedback = feedback_tracker.get_latest_feedback()
        if latest_feedback:
            decider_feedback = latest_feedback.get("decider_feedback") or latest_feedback.get("recommended_adjustments")
            if isinstance(decider_feedback, str):
                decider_feedback = decider_feedback.strip()
                if decider_feedback.lower() == "null":
                    decider_feedback = ""
                else:
                    try:
                        decider_feedback = json.loads(decider_feedback)
                    except Exception:
                        # keep as plain string
                        pass
            if isinstance(decider_feedback, (dict, list)):
                try:
                    feedback_context = json.dumps(decider_feedback, indent=2)
                except Exception:
                    feedback_context = str(decider_feedback)
            elif decider_feedback:
                feedback_context = str(decider_feedback)
    except Exception as feedback_err:
        feedback_context = f"Unable to load recent feedback: {feedback_err}"
        print(f"⚠️  Failed to build decider feedback context: {feedback_err}")

    # Separate cash and stock holdings
    cash_balance = next((h['current_value'] for h in holdings if h['ticker'] == 'CASH'), 0)
    stock_holdings = [h for h in holdings if h['ticker'] != 'CASH']
    
    # Enhanced holdings display with performance metrics
    holdings_text = ""
    if stock_holdings:
        holdings_parts = []
        for h in stock_holdings:
            gain_loss_pct = (h['gain_loss'] / h['total_value'] * 100) if h['total_value'] > 0 else 0
            holdings_parts.append(
                f"{h['ticker']}: {h['shares']} shares at ${h['purchase_price']:.2f} "
                f"→ Current: ${h['current_price']:.2f} "
                f"(Gain/Loss: ${h['gain_loss']:.2f} / {gain_loss_pct:.1f}%) "
                f"(Value: ${h['current_value']:.2f}) "
                f"(Reason: {h['reason']})"
            )
        holdings_text = "\n".join(holdings_parts)
    else:
        holdings_text = "No current stock holdings."
    
    # Calculate available funds and pacing stats
    available_cash = cash_balance
    total_portfolio_value = available_cash + sum(h.get("total_value", 0) for h in stock_holdings)

    account_mode = "MARGIN" if IS_MARGIN_ACCOUNT else "CASH"
    settled_cash_prompt = cash_balance

    try:
        if account_mode == "MARGIN" or get_trading_mode() in {"live", "real_world"}:
            from trading_interface import trading_interface
            snapshot = trading_interface.sync_schwab_positions()
            if snapshot and snapshot.get("status") == "success":
                raw_settled_prompt = float(
                    snapshot.get("cash_balance")
                    or snapshot.get("cash_balance_settled")
                    or snapshot.get("settled_cash_strict")
                    or settled_cash_prompt
                )
                unsettled_cash_prompt = float(snapshot.get("unsettled_cash") or 0.0)
                settled_cash_prompt = max(raw_settled_prompt - unsettled_cash_prompt, 0.0)
    except Exception as sync_error:
        print(f"⚠️  Unable to refresh Schwab funds for prompt: {sync_error}")
    settled_cash_value = settled_cash_prompt

    daily_usage = get_daily_trade_usage(config_hash)
    minutes_since_last_entry_value = daily_usage.get("minutes_since_last_entry")
    minutes_since_last_entry_str = (
        str(minutes_since_last_entry_value)
        if minutes_since_last_entry_value is not None
        else "none"
    )
    tickers_entered_today_list = daily_usage.get("tickers_entered_today", [])
    tickers_entered_today_str = ", ".join(tickers_entered_today_list) if tickers_entered_today_list else "none"

    template_has_holdings = "{holdings}" in user_prompt_template
    template_has_summaries = "{summaries}" in user_prompt_template
    template_has_momentum = "{momentum_recap}" in user_prompt_template
    template_has_feedback = "{feedback_context}" in user_prompt_template
    template_has_cash = ("{settled_cash}" in user_prompt_template) or ("${settled_cash}" in user_prompt_template)
    template_has_available_cash = "{available_cash}" in user_prompt_template

    user_prompt_values = {
        "account_mode": account_mode,
        "settled_cash": f"{settled_cash_prompt:,.2f}",
        "daily_ticket_cap": DAILY_TICKET_CAP,
        "daily_buy_cap": DAILY_BUY_CAP,
        "today_tickets_used": daily_usage.get("today_tickets_used", 0),
        "today_buys_used": daily_usage.get("today_buys_used", 0),
        "minutes_since_last_entry": minutes_since_last_entry_str,
        "tickers_entered_today": tickers_entered_today_str,
        "min_entry_spacing_min": MIN_ENTRY_SPACING_MIN,
        "reentry_cooldown_min": REENTRY_COOLDOWN_MIN,
        "min_buy": f"{int(MIN_BUY_AMOUNT):,}",
        "typical_buy_low": f"{int(TYPICAL_BUY_LOW):,}",
        "typical_buy_high": f"{int(TYPICAL_BUY_HIGH):,}",
        "max_buy": f"{int(MAX_BUY_AMOUNT):,}",
        "settled_cash_value": f"{settled_cash_value:,.2f}",
        "min_buy_amount": f"{MIN_BUY_AMOUNT:,.0f}",
        "holdings": holdings_text,
        "available_cash": f"{available_cash:,.2f}",
        "summaries": summarized_text,
        "momentum_recap": momentum_recap,
        "feedback_context": feedback_context,
    }
    prompt = safe_format_template(user_prompt_template, user_prompt_values)
    auto_context_sections = []
    if not template_has_cash:
        auto_context_sections.append(f"Settled cash available: ${settled_cash_prompt:,.2f} (min buy ${MIN_BUY_AMOUNT:,.0f})")
    if not template_has_available_cash:
        auto_context_sections.append(f"Cash on hand (incl. unsettled): ${available_cash:,.2f}")
    if not template_has_holdings:
        auto_context_sections.append(f"Holdings snapshot:\n{holdings_text}")
    if not template_has_summaries:
        auto_context_sections.append("Summaries digest:\n" + summarized_text)
    if not template_has_momentum:
        auto_context_sections.append("Momentum recap:\n" + momentum_recap)
    if not template_has_feedback and feedback_context and feedback_context.strip():
        auto_context_sections.append("Feedback context:\n" + feedback_context.strip())
    if auto_context_sections:
        prompt += "\n\n# Auto-context (missing fields in prompt template)\n" + "\n\n".join(auto_context_sections)
    prompt += (
        "\n\nCASH & PROFIT-TAKING DISCLOSURE:"
        f" If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value:,.2f} and min buy ${MIN_BUY_AMOUNT:,.0f}),"
        " you must add a top-level \"cash_reason\" that (a) states why no BUY (caps, cooldown, min-buy unmet, lack of edge, etc.)"
        " and (b) confirms that every ≥+3% winner was harvested or explicitly names any retained winner with its % gain and fresh catalyst justification."
        " Keep the object compact: {\"decisions\":[...], \"cash_reason\":\"...\"}."
    )


    prompt_preview_head = int(os.getenv("DAI_PROMPT_DEBUG_HEAD", os.getenv("DAI_PROMPT_DEBUG_LIMIT", "10000")))
    prompt_preview_tail = int(os.getenv("DAI_PROMPT_DEBUG_TAIL", "5000"))
    prompt_coverage = prompt_preview_head + prompt_preview_tail
    if len(prompt) <= prompt_coverage:
        prompt_snippet = prompt
        shown_chars = len(prompt)
    else:
        head = prompt[:prompt_preview_head]
        tail = prompt[-prompt_preview_tail:] if prompt_preview_tail > 0 else ""
        prompt_snippet = "".join([head, "\n… [middle omitted]\n", tail])
        shown_chars = min(len(prompt), prompt_coverage)

    print(f"🧠 Decider prompt preview (showing {shown_chars} of {len(prompt)} chars | head {prompt_preview_head}, tail {prompt_preview_tail}):\n{prompt_snippet}")
    if len(prompt) > prompt_coverage:
        print("… (prompt truncated for console preview)")
    print(f"🧠 Decider prompt (full {len(prompt)} chars):\n{prompt}")
    
    # Build explicit list/map of required decisions for current holdings
    holdings_by_ticker = {h['ticker'].upper(): h for h in stock_holdings}
    current_tickers = [h['ticker'].upper() for h in stock_holdings] if stock_holdings else []
    current_ticker_set = set(current_tickers)
    
    # Show what AI is being told
    if current_tickers:
        print(f"💼 Current Holdings AI MUST Analyze: {', '.join(current_tickers)}")
    else:
        print(f"💼 Portfolio: NO positions (cash only)")
    
    # Create clear instructions with actual ticker examples
    # Logging current holdings – informational only
    if current_tickers:
        print(f"🚨 YOU CURRENTLY OWN: {', '.join(current_tickers)}")
    else:
        print('✅ You have NO current positions - scanning for new setups')


    
    # Debug: Print first 300 chars of prompt
    print(f"📝 Prompt preview: {prompt[:300]}...")
    
    # Import the JSON schema for structured responses
    # Get AI decision regardless of market status
    cash_hold_reason = None
    ai_response = prompt_manager.ask_openai(
        prompt, 
        system_prompt, 
        agent_name="DeciderAgent"
    )
    print(f"🗒️ Parsed Decider response ({type(ai_response).__name__}): {ai_response}")
    
    # Ensure response is always a list
    if isinstance(ai_response, dict):
        if isinstance(ai_response.get("cash_reason"), str) and ai_response.get("cash_reason").strip():
            cash_hold_reason = ai_response.get("cash_reason").strip()
        # Check if it's an error response first
        if 'error' in ai_response:
            print(f"❌ AI returned error: {ai_response.get('error')}")
            ai_response = []
        # Check if GPT-5 returned {"decisions": [...]} format
        elif 'decisions' in ai_response and isinstance(ai_response['decisions'], list):
            print(f"📦 Extracting decisions array from GPT-5 response object")
            ai_response = ai_response['decisions']
        else:
            # Convert single dict to list (sometimes returns single decision as dict)
            print(f"📦 Converting single decision dict to list format")
            ai_response = [ai_response]
    elif not isinstance(ai_response, list):
        print(f"⚠️  Unexpected response type: {type(ai_response)}, converting to list")
        ai_response = [ai_response] if ai_response else []

    # Drop HOLD decisions for tickers we don't own (e.g., "PORTFOLIO", "CASH")
    if current_ticker_set:
        filtered_decisions = []
        for decision in ai_response:
            if not isinstance(decision, dict):
                filtered_decisions.append(decision)
                continue
            action = (decision.get("action") or "").lower()
            ticker = (decision.get("ticker") or "").upper()
            if action == "hold" and ticker and ticker not in current_ticker_set:
                print(f"⚠️  Dropping hallucinated HOLD for unknown ticker '{ticker}'")
                continue
            filtered_decisions.append(decision)
        ai_response = filtered_decisions

    # Guarantee a decision exists for every current holding
    existing_decisions = {}
    for decision in ai_response:
        if isinstance(decision, dict):
            ticker = (decision.get("ticker") or "").upper()
            if ticker:
                existing_decisions[ticker] = decision

    missing_tickers = [ticker for ticker in current_ticker_set if ticker not in existing_decisions]

    if missing_tickers:
        print(f"⚠️  AI omitted decisions for: {', '.join(missing_tickers)} — auto-filling HOLD entries.")
        def fmt_num(val):
            try:
                return f"{float(val):,.2f}"
            except (TypeError, ValueError):
                return "?"
        for ticker in missing_tickers:
            holding = holdings_by_ticker.get(ticker)
            shares_txt = fmt_num(holding.get("shares")) if holding else "?"
            basis_txt = fmt_num(holding.get("purchase_price")) if holding else "?"
            last_txt = fmt_num(holding.get("current_price")) if holding else "?"
            gl_txt = fmt_num(holding.get("gain_loss")) if holding else "?"
            ai_response.append({
                "action": "hold",
                "ticker": ticker,
                "amount_usd": 0,
                "reason": (
                    f"Auto HOLD {ticker}: AI omitted this position "
                    f"({shares_txt} sh @ ${basis_txt}, last ${last_txt}, G/L ${gl_txt}). "
                    "Carry forward to next cycle with explicit reasoning."
                )
            })

    forced_override_notes = enforce_profit_taking_guardrail(ai_response, holdings_by_ticker)
    if forced_override_notes:
        print(f"🛡️  Profit-taking guardrail executed for: {', '.join(forced_override_notes)}")

    # If no buys and settled funds are available, surface the AI's cash rationale (or warn if missing)
    buy_actions = [
        d for d in ai_response
        if isinstance(d, dict) and (d.get("action") or "").lower() == "buy" and float(d.get("amount_usd") or 0) > 0
    ]
    if settled_cash_value >= MIN_BUY_AMOUNT and not buy_actions:
        if cash_hold_reason:
            print(f"💬 Cash hold rationale (no buys with ${settled_cash_value:,.2f} settled): {cash_hold_reason}")
        else:
            print(f"⚠️  No buys chosen despite ${settled_cash_value:,.2f} settled; AI did not supply a cash_reason.")

    # If market is closed, modify decisions to show they're deferred
    if not market_open:
        print("🕒 Market closed - Decisions recorded but execution deferred")
        # Modify each decision to indicate deferred execution
        for decision in ai_response:
            if isinstance(decision, dict) and decision.get('action') not in ['N/A', 'hold']:
                original_reason = decision.get('reason', '')
                # Only add prefix if not already present (avoid double prefix)
                if not original_reason.startswith('⛔ MARKET CLOSED'):
                    decision['reason'] = f"⛔ MARKET CLOSED - No action taken. AI suggested: {original_reason}"
                    decision['execution_status'] = 'market_closed'
    
    return ai_response

def log_sell_analysis(decisions, holdings):
    """Log explicit reasoning for each existing position - sell or hold decision"""
    print("\n" + "="*50)
    print("📊 SELL ANALYSIS FOR EXISTING POSITIONS")
    print("="*50)
    
    stock_holdings = [h for h in holdings if h['ticker'] != 'CASH']
    
    if not stock_holdings:
        print("✅ No existing positions to analyze")
        return
    
    # Create a map of decisions by ticker
    decision_map = {d.get('ticker', '').upper(): d for d in decisions if isinstance(d, dict)}
    
    for holding in stock_holdings:
        ticker = holding['ticker']
        current_value = holding.get('current_value', 0)
        gain_loss = holding.get('gain_loss', 0)
        gain_loss_pct = (gain_loss / holding['total_value'] * 100) if holding.get('total_value', 0) > 0 else 0
        
        decision = decision_map.get(ticker.upper())
        
        if decision:
            action = decision.get('action', 'unknown')
            reason = decision.get('reason', 'No reason provided')
            
            if action == 'sell':
                print(f"🔴 SELL {ticker}: {reason}")
            elif action == 'hold':
                print(f"🟡 HOLD {ticker}: {reason}")
            else:
                print(f"❓ {action.upper()} {ticker}: {reason}")
        else:
            print(f"⚠️  NO DECISION for {ticker} (Value: ${current_value:.2f}, G/L: {gain_loss_pct:.1f}%) - AI SHOULD HAVE PROVIDED SELL/HOLD REASONING")
    
    print("="*50 + "\n")

def extract_decision_info_from_text(text_content):
    """Try to extract decision info from malformed text responses"""
    import re
    import json
    
    # First try to extract JSON-like structures and fix common issues
    try:
        text_str = str(text_content)
        
        # Try to find JSON objects in the text
        json_pattern = r'\{[^{}]*\}'
        json_matches = re.findall(json_pattern, text_str)
        
        for json_str in json_matches:
            try:
                # Try to parse the JSON
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    # Fix field name inconsistencies - 'reasoning' should be 'reason'
                    if 'reasoning' in parsed and 'reason' not in parsed:
                        parsed['reason'] = parsed.pop('reasoning')
                    
                    # Check if it has the required fields
                    if 'action' in parsed and parsed.get('action'):
                        # Set defaults for missing fields
                        if 'ticker' not in parsed:
                            parsed['ticker'] = 'SPY'  # Default to SPY if no ticker
                        if 'amount_usd' not in parsed and 'amount' not in parsed:
                            parsed['amount_usd'] = 0 if parsed['action'] == 'hold' else 1000
                        elif 'amount' in parsed and 'amount_usd' not in parsed:
                            parsed['amount_usd'] = parsed.pop('amount')
                        if 'reason' not in parsed:
                            parsed['reason'] = f"Extracted from response: {text_str[:50]}..."
                        
                        print(f"✅ Successfully parsed JSON with field fixes: {parsed}")
                        return parsed
                        
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"⚠️  Error in JSON extraction: {e}")
    
    # Fallback to regex pattern matching
    action_pattern = r'\b(buy|sell|hold)\s+([A-Z]{1,5})\b'
    amount_pattern = r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)'
    
    matches = re.findall(action_pattern, str(text_content), re.IGNORECASE)
    amounts = re.findall(amount_pattern, str(text_content))
    
    if matches:
        action, ticker = matches[0]
        amount = float(amounts[0].replace(',', '')) if amounts else 1000
        return {
            "action": action.lower(),
            "ticker": ticker.upper(),
            "amount_usd": amount,
            "reason": f"Extracted from malformed response: {str(text_content)[:100]}..."
        }
    return None

def store_trade_decisions(decisions, run_id):
    config_hash = get_current_config_hash()
    print(f"🔍 Storing decisions for {config_hash}: {decisions}")
    
    # CRITICAL: VALIDATE decisions to prevent AI hallucinations
    from decision_validator import DecisionValidator
    
    # Get current portfolio state for validation
    current_holdings = fetch_holdings()
    stock_holdings = [h for h in current_holdings if h['ticker'] != 'CASH']
    cash_balance = next((h['current_value'] for h in current_holdings if h['ticker'] == 'CASH'), 0)
    
    # Validate all decisions
    validator = DecisionValidator(
        stock_holdings,
        cash_balance,
        allow_sell_reuse=IS_MARGIN_ACCOUNT
    )
    validated_decisions, rejected_decisions = validator.validate_decisions(decisions)
    
    # Check if AI missed any holdings
    missing_holdings = validator.get_missing_holdings_decisions(validated_decisions)
    
    # Log rejected decisions
    if rejected_decisions:
        print(f"⚠️  REJECTED {len(rejected_decisions)} INVALID DECISIONS:")
        for rej in rejected_decisions:
            print(f"   ❌ {rej['validation_error']}")
    
    # Use validated decisions only
    decisions = validated_decisions
    
    # Enrich decisions with shares and total_value for better display
    print("💎 Enriching decisions with shares and dollar values...")
    for decision in decisions:
        if isinstance(decision, dict):
            action = decision.get('action', '').lower()
            ticker = decision.get('ticker', '').upper()
            
            if action == 'sell' or action == 'hold':
                # Look up current holding to get shares and value
                holding = next((h for h in stock_holdings if h['ticker'].upper() == ticker), None)
                if holding:
                    shares = holding.get('shares', 0)
                    value = holding.get('current_value', 0)
                    decision['shares'] = shares
                    decision['total_value'] = value
                    if action == 'sell':
                        decision['amount_usd'] = value  # Selling full position
                    print(f"   ✅ {action.upper()} {ticker}: {shares} shares, ${value:.2f}")
                else:
                    print(f"   ⚠️  {action.upper()} {ticker}: No holding found to enrich")
            elif action == 'buy':
                # For buys, calculate estimated shares
                amount = decision.get('amount_usd', 0)
                if amount > 0:
                    price = get_current_price(ticker)
                    if price:
                        estimated_shares = int(amount / price)
                        decision['shares'] = estimated_shares
                        decision['total_value'] = amount
                        print(f"   ✅ BUY {ticker}: {estimated_shares} shares (est.), ${amount:.2f}")
                    else:
                        print(f"   ⚠️  BUY {ticker}: Cannot get price for share calculation")
    
    # CRITICAL: Check market hours and modify decisions BEFORE storing
    market_open = is_market_open()
    if not market_open:
        pacific_now = datetime.now(PACIFIC_TIMEZONE)
        eastern_now = pacific_now.astimezone(EASTERN_TIMEZONE)
        print(f"⛔ MARKET CLOSED at {eastern_now.strftime('%I:%M %p ET')} - Marking all decisions as deferred")
    
    # Filter out error responses before storing
    valid_decisions = []
    for decision in decisions:
        if isinstance(decision, dict) and 'error' in decision:
            print(f"⚠️  Skipping error response: {decision.get('error', 'Unknown error')}")
            continue
        if isinstance(decision, dict) and decision.get('action') and decision.get('ticker'):
            # MODIFY decision if market is closed (only if not already marked)
            if not market_open:
                action = decision.get('action', '').lower()
                if action in ['buy', 'sell', 'hold']:
                    original_reason = decision.get('reason', 'No reason provided')
                    if action == 'hold':
                        prefix = "⛔ MARKET CLOSED - Hold recorded for visibility. AI suggested: "
                    else:
                        prefix = "⛔ MARKET CLOSED - No action taken. AI suggested: "
                    # Only add prefix if not already present (avoid double prefix)
                    if not original_reason.startswith('⛔ MARKET CLOSED'):
                        decision['reason'] = f"{prefix}{original_reason}"
                        decision['execution_status'] = 'market_closed'
                        print(f"   Modified {action.upper()} {decision.get('ticker')} → MARKET CLOSED")
                    else:
                        print(f"   Already marked: {action.upper()} {decision.get('ticker')}")
            
            valid_decisions.append(decision)
        else:
            print(f"⚠️  Invalid decision format: {decision}")
            # Try to extract info from malformed decision
            extracted = extract_decision_info_from_text(decision)
            if extracted:
                print(f"✅ Extracted: {extracted}")
                # Also mark extracted decisions if market closed
                if not market_open and extracted.get('action', '').lower() in ['buy', 'sell', 'hold']:
                    action = extracted.get('action', '').lower()
                    original_reason = extracted.get('reason', '')
                    if action == 'hold':
                        prefix = "⛔ MARKET CLOSED - Hold recorded for visibility. AI suggested: "
                    else:
                        prefix = "⛔ MARKET CLOSED - No action taken. AI suggested: "
                    extracted['reason'] = f"{prefix}{original_reason}"
                    extracted['execution_status'] = 'market_closed'
                valid_decisions.append(extracted)
    
    # Only store if we have valid decisions
    # Log sell analysis for transparency regardless of validity
    try:
        current_holdings = fetch_holdings()
        log_sell_analysis(valid_decisions, current_holdings)
    except Exception as e:
        print(f"⚠️  Could not log sell analysis: {e}")
    
    if not valid_decisions:
        print("❌ No valid trade decisions to store - AI response was malformed")
        # Try to extract info from the entire response text
        print(f"📋 Attempting to extract from full response: {decisions}")
        extracted_from_full = extract_decision_info_from_text(str(decisions))
        
        if extracted_from_full:
            print(f"✅ Extracted from full response: {extracted_from_full}")
            # If market is closed, modify the reason
            if not market_open:
                action = extracted_from_full.get('action', '').lower()
                if action in ['buy', 'sell', 'hold']:
                    original_reason = extracted_from_full.get('reason', '')
                    if action == 'hold':
                        prefix = "⛔ MARKET CLOSED - Hold recorded for visibility. AI suggested: "
                    else:
                        prefix = "⛔ MARKET CLOSED - No action taken. AI suggested: "
                    extracted_from_full["reason"] = f"{prefix}{original_reason}"
                    extracted_from_full['execution_status'] = 'market_closed'
            valid_decisions = [extracted_from_full]
        else:
            # Absolute fallback
            fallback_decision = {
                "action": "hold",
                "ticker": "SPY",  # Use SPY instead of UNKNOWN
                "amount_usd": 0,
                "reason": "AI response was completely unparseable - defaulting to hold SPY"
            }
            
            if not market_open:
                fallback_decision["reason"] = "⛔ MARKET CLOSED - No action taken (AI response was unparseable)"
            
            valid_decisions = [fallback_decision]
    
    # Get current Pacific time as NAIVE timestamp (dashboard will format it correctly)
    pacific_now = datetime.now(PACIFIC_TIMEZONE)
    # Remove timezone info so PostgreSQL stores it as-is without converting to UTC
    naive_pacific_timestamp = pacific_now.replace(tzinfo=None)
    
    print(f"🕐 Storing timestamp (naive Pacific): {pacific_now.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
    
    # Debug: Show what's being stored
    print(f"💾 Storing {len(valid_decisions)} decisions to database:")
    for vd in valid_decisions:
        ticker = vd.get('ticker', 'N/A')
        action = vd.get('action', 'N/A')
        shares = vd.get('shares', 'NO_SHARES_FIELD')
        amount = vd.get('amount_usd', 'NO_AMOUNT')
        total_val = vd.get('total_value', 'NO_TOTAL')
        print(f"   - {action.upper()} {ticker}: shares={shares}, amount_usd={amount}, total_value={total_val}")
    
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trade_decisions (
                id SERIAL PRIMARY KEY,
                config_hash VARCHAR(50) NOT NULL,
                run_id TEXT,
                timestamp TIMESTAMP,
                data JSONB
            )
        """))
        conn.execute(text("""
            INSERT INTO trade_decisions (run_id, timestamp, data, config_hash) VALUES (:run_id, :timestamp, :data, :config_hash)
        """), {
            "run_id": run_id,
            "timestamp": naive_pacific_timestamp,
            "data": json.dumps(valid_decisions),
            "config_hash": get_current_config_hash()
        })
        print(f"✅ Stored to trade_decisions table with enriched data")

    return valid_decisions

if __name__ == "__main__":
    # Get unprocessed summaries instead of just the latest run
    unprocessed_summaries = get_unprocessed_summaries()
    
    if not unprocessed_summaries:
        print("No unprocessed summaries found.")
        # Still record initial portfolio snapshot
        try:
            record_portfolio_snapshot()
            print("Initial portfolio snapshot recorded")
        except Exception as e:
            print(f"Failed to record initial snapshot: {e}")
        
        # Create empty run and proceed to decision making (will record N/A if market closed)
        pacific_now = datetime.now(PACIFIC_TIMEZONE)
        run_id = pacific_now.strftime("%Y%m%dT%H%M%S") + "_no_summaries"
        unprocessed_summaries = []  # Empty list will trigger market status check
    else:
        print(f"Found {len(unprocessed_summaries)} unprocessed summaries")
    
        # Determine target run_id from summaries (prefer actual run metadata)
        run_id_candidates = []
        for summary in unprocessed_summaries:
            summary_run_id = summary.get('run_id')
            summary_timestamp = summary.get('timestamp')
            if summary_run_id:
                run_id_candidates.append((summary_timestamp, summary_run_id))
        if run_id_candidates:
            run_id_candidates.sort(key=lambda item: item[0] or datetime.min)
            run_id = run_id_candidates[-1][1]
            unprocessed_summaries = [s for s in unprocessed_summaries if s.get('run_id') == run_id] or unprocessed_summaries
            print(f"Processing run {run_id} with {len(unprocessed_summaries)} summaries")
        else:
            latest_timestamp = max((s.get('timestamp') for s in unprocessed_summaries if s.get('timestamp')), default=None)
            run_id = latest_timestamp.strftime("%Y%m%dT%H%M%S") if latest_timestamp else datetime.now().strftime("%Y%m%dT%H%M%S")
        
        # Update current prices before making decisions
        update_all_current_prices()
        
        holdings = fetch_holdings()
        
        # Check if we have current prices for decision making
        holdings_without_prices = [h for h in holdings if h['ticker'] != 'CASH' and h['current_price'] == h['purchase_price']]
        if holdings_without_prices:
            tickers_without_prices = [h['ticker'] for h in holdings_without_prices]
            print(f"\n⚠️  WARNING: Using purchase prices for decision making on: {', '.join(tickers_without_prices)}")
            print("💡 Consider manually updating prices for accurate decision making")

        decisions = ask_decision_agent(unprocessed_summaries, run_id, holdings)
        validated_decisions = store_trade_decisions(decisions, run_id)

        # Execute trades through the unified trading interface
        try:
            from trading_interface import trading_interface
            execution_results = trading_interface.execute_trade_decisions(validated_decisions)

            # Log execution results
            if execution_results.get("summary"):
                summary = execution_results["summary"]
                print(f"🔄 Trade Execution Summary:")
                print(f"   📊 Simulation: {summary['simulation_executed']} executed")
                if summary.get('live_executed', 0) > 0:
                    print(f"   💰 Live: {summary['live_executed']} executed")
                if summary.get('skipped', 0) > 0:
                    print(f"   ⏭️  Skipped: {summary['skipped']}")
                if summary.get('errors', 0) > 0:
                    print(f"   ❌ Errors: {summary['errors']}")
        except ImportError:
            # Fallback to original method if trading_interface is not available
            print("⚠️  Trading interface not available, using simulation only")
            update_holdings(validated_decisions)
        except Exception as e:
            print(f"❌ Error in trading interface: {e}")
            print("🔄 Falling back to simulation mode")
            update_holdings(validated_decisions)

        # Mark summaries as processed
        summary_ids = [s['id'] for s in unprocessed_summaries]
        mark_summaries_processed(summary_ids)

        # Record portfolio snapshot after trades
        try:
            record_portfolio_snapshot()
            print("Portfolio snapshot recorded after trades")
        except Exception as e:
            print(f"Failed to record portfolio snapshot: {e}")

        print(f"Stored decisions and updated holdings for run {run_id}")
        print(f"Marked {len(summary_ids)} summaries as processed")
