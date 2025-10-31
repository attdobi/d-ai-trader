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
from sqlalchemy import text
from config import engine, PromptManager, session, openai, get_current_config_hash, get_trading_mode, set_gpt_model
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

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

# Initialize feedback tracker
feedback_tracker = TradeOutcomeTracker()


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

def update_holdings(decisions, skip_live_execution=False):
    # Use Pacific time as naive timestamp (database stores as-is, dashboard formats correctly)
    pacific_now = datetime.now(PACIFIC_TIMEZONE)
    timestamp = pacific_now.replace(tzinfo=None)  # Store as naive Pacific time
    skipped_decisions = []
    trading_mode = get_trading_mode()
    config_hash = get_current_config_hash()
    one_trade_mode = _os.getenv("DAI_ONE_TRADE_MODE", "0") == "1"
    allowed_buy_idx = None

    live_execution_enabled = trading_mode == "real_world" and not skip_live_execution

    def _sync_live_positions(stage):
        if not live_execution_enabled:
            return
        try:
            from trading_interface import trading_interface
            print(f"🔄 Syncing Schwab positions ({stage})...")
            trading_interface.sync_schwab_positions(persist=True)
        except Exception as exc:
            print(f"⚠️  Schwab sync ({stage}) failed: {exc}")

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
        # Use Pacific time for run_id consistency
        pacific_now = datetime.now(PACIFIC_TIMEZONE)
        run_id = pacific_now.strftime("%Y%m%dT%H%M%S")
        store_trade_decisions(skipped_decisions, f"{run_id}_skipped")
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
            shares = floor(amount / price)
            if shares == 0:
                print(f"Skipping buy for {ticker} due to insufficient funds for 1 share (need ${price:.2f}, have ${amount:.2f}).")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Insufficient funds for 1 share (need ${price:.2f}, allocated ${amount:.2f}) - no trade executed (Original: {reason})"
                })
                continue

            # Calculate actual spend - prioritize using the requested dollar amount over exact shares
            # If the AI requested $1000 for a $800 stock, buy 1 share for $800, not skip the trade
            actual_spent = min(amount, shares * price)
            shares = floor(actual_spent / price)  # Recalculate shares based on actual spend
            if available_cash - actual_spent < MIN_BUFFER:
                print(f"Skipping buy for {ticker} - would exceed budget (need ${actual_spent:.2f}, available ${available_cash:.2f})")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Budget exceeded - no trade executed (Original: {reason})"
                })
                continue

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
    # Get versioned prompt for DeciderAgent
    from prompt_manager import get_active_prompt
    try:
        prompt_data = get_active_prompt("DeciderAgent")
        system_prompt = prompt_data["system_prompt"]
        user_prompt_template = prompt_data["user_prompt_template"]
        prompt_version = prompt_data["version"]
        print(f"🔧 Using DeciderAgent prompt v{prompt_version} (UNIFIED)")
        
        # DEBUG: Check if prompt is confusing the AI
        if "holdings" in user_prompt_template.lower() and "json array" not in user_prompt_template.lower():
            print(f"⚠️  WARNING: Prompt v{prompt_version} might confuse AI - using fallback instead")
            raise Exception("Prompt appears to confuse AI - using fallback")
        
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
        # Build system prompt with ACTUAL holdings list
        current_tickers_for_system = [h['ticker'] for h in stock_holdings] if stock_holdings else []
        holdings_list = ', '.join(current_tickers_for_system) if current_tickers_for_system else 'NONE'
        
        # Fallback to AGGRESSIVE DAY TRADING prompt
        system_prompt = f"""You are an AGGRESSIVE day trading AI optimized for SHORT-TERM PROFITS.

🚨 CRITICAL - YOUR CURRENT PORTFOLIO:
You currently own ONLY these stocks: {holdings_list}
You can ONLY sell stocks you own. You CANNOT sell stocks not in the list above.

DAY TRADING PHILOSOPHY:
- Multiple trades per day is GOOD (this system runs every 15-60 minutes)
- Take profits QUICKLY on 5%+ gains - don't be greedy
- Cut losses FAST at -3% to -5% - protect capital
- MOMENTUM is everything - ride trends but exit before reversals
- Cash is a position - holding cash while waiting for setups is SMART

You are NOT a long-term investor. You are a DAY TRADER seeking 2-10% gains on each trade."""

        user_prompt_template = """You are an AGGRESSIVE DAY TRADING AI managing a $10,000 portfolio.

🔥 DAY TRADING CORE RULES:

AGGRESSIVE PROFIT TAKING (We trade MULTIPLE times per day):
- ✅ SELL at 5-8% profit - Lock in quick wins!
- ✅ SELL at 8-15% profit - Great day trade!
- ✅ SELL at 15%+ profit - Exceptional win, take it NOW!
- ⚠️  HOLD only if strong momentum continues AND news supports more upside
- ❌ CUT LOSSES at -3% to -5% - Protect capital for next opportunity

POSITION SIZING (Maximize opportunities):
- MINIMUM buy: $1500 (ensures meaningful profit on 5% gains)
- OPTIMAL buy: $2000-$3500 (balanced for multiple positions)
- MAXIMUM buy: $4000 (for high-conviction plays)
- Available cash: ${available_cash} - DEPLOY IT!

AVOID FOMO ENTRIES:
- ❌ Do NOT chase all-time highs or vertical pops right after bullish news/earnings
- ✅ Prefer pullbacks to support, consolidations, or breakouts with fresh momentum confirmation
- ✅ If price is already stretched 5%+ above the prior day close, wait for a better setup

PORTFOLIO RULES:
- Max 5 stocks at once (allows diversification and quick rotation)
- NEVER add to existing positions - Sell first, then re-buy if still bullish
- OK to hold cash while scanning for next setup
- Make EVERY position count - if uncertain, wait for better setup

DECISION PROCESS FOR EXISTING POSITIONS:
For EACH stock in "Current Holdings":
1. Check current profit/loss %
2. Evaluate momentum (is the move continuing or fading?)
3. Check news for new catalysts or risks
4. DECISION: SELL (take profits/cut losses) or HOLD (momentum continues)

Then consider NEW opportunities from market analysis.

Current Portfolio:
- Available Cash: ${available_cash} (out of $10,000 total)
- Current P/L Summary:
{pnl_summary}
- Current Holdings: {holdings}

Market Analysis:
{summaries}

Performance Feedback:
{feedback}

🚨 MANDATORY: For EVERY stock in "Current Holdings", provide SELL or HOLD decision with reasoning.

🚨 JSON RESPONSE FORMAT (NO EXCEPTIONS):
[
  {{
    "action": "sell" or "buy" or "hold",
    "ticker": "SYMBOL",
    "amount_usd": dollar_amount,
    "reason": "detailed explanation"
  }}
]

AMOUNT RULES:
- SELL: amount_usd = 0 (sell ALL shares)
- BUY: amount_usd = $1500 to $4000 (substantial amounts only)
- HOLD: amount_usd = 0 (but explain WHY not selling)

EXAMPLES OF AGGRESSIVE DAY TRADING DECISIONS:
✅ {{"action": "sell", "ticker": "NVDA", "amount_usd": 0, "reason": "DAY TRADE: Up 6% since this morning, taking profits before potential reversal"}}
✅ {{"action": "sell", "ticker": "TSLA", "amount_usd": 0, "reason": "DAY TRADE: Hit 8% gain target, locking in $240 profit"}}
✅ {{"action": "buy", "ticker": "AMD", "amount_usd": 3000, "reason": "MOMENTUM PLAY: Breaking out on chip deal news, targeting 5-10% quick gain"}}
✅ {{"action": "sell", "ticker": "BA", "amount_usd": 0, "reason": "STOP LOSS: Down 4%, cutting losses to preserve capital"}}
✅ {{"action": "hold", "ticker": "AAPL", "amount_usd": 0, "reason": "STRONG MOMENTUM: Up 3% with positive news flow, holding for 8-10% target"}}

EXAMPLES OF BAD DECISIONS:
❌ {{"action": "hold", "ticker": "SPY", "amount_usd": 0, "reason": "Long-term investment"}} ← We're DAY TRADING, not investing!
❌ {{"action": "hold", "ticker": "NVDA", "amount_usd": 0, "reason": "Up 12% but will hold for more"}} ← TAKE PROFITS! 12% is great!
❌ {{"action": "buy", "ticker": "GLD", "amount_usd": 305, "reason": "..."}} ← TOO SMALL!
❌ {{"action": "buy", "ticker": "TSLA", "amount_usd": 800, "reason": "..."}} ← TOO SMALL (under $1500 minimum)

No explanatory text, no markdown, just pure JSON array."""
    
    # Check market status for later use
    market_open = is_market_open()
    if not market_open:
        print("📈 Market is CLOSED - Will analyze summaries but defer execution")
    else:
        print("📈 Market is OPEN - Will analyze summaries and execute trades")
    
    parsed_summaries = []
    
    # Limit the number of summaries to process to avoid rate limiting
    # Process only the most recent summaries
    max_summaries = 10
    if len(summaries) > max_summaries:
        summaries = summaries[-max_summaries:]  # Take the most recent ones
        print(f"Processing only the {max_summaries} most recent summaries to avoid rate limiting")
    
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
    for s in parsed_summaries:
        agent_label = (s.get('agent') or 'unknown').strip().lower()
        headlines_text = ', '.join(s['headlines'][:3])  # Limit to 3 headlines per agent
        insights_text = s['insights'] if len(s['insights']) <= SUMMARY_MAX_CHARS else s['insights'][:SUMMARY_MAX_CHARS] + "... [truncated]"
        summary_parts.append(f"{agent_label}: {headlines_text} | {insights_text}")

    summarized_text = "\n".join(summary_parts)
    print(f"📰 Summaries forwarded to Decider: {len(parsed_summaries)}")

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
    
    # Calculate available funds
    available_cash = cash_balance
    max_spendable = max(0, available_cash - MIN_BUFFER)
    total_portfolio_value = available_cash + sum(h.get("total_value", 0) for h in stock_holdings)

    # Get feedback from recent performance (simplified to reduce tokens)
    feedback_context = ""
    try:
        latest_feedback = feedback_tracker.get_latest_feedback()
        if latest_feedback:
            feedback_context = f"Recent Success Rate: {latest_feedback['success_rate']:.1%}, Avg Profit: {latest_feedback['avg_profit_percentage']:.2%}"
        else:
            feedback_context = "No recent performance data available."
    except Exception as e:
        print(f"Failed to get feedback context: {e}")
        feedback_context = "Feedback system unavailable."


    pl_lines = []
    for h in stock_holdings:
        try:
            ticker = h.get('ticker', 'UNKNOWN')
            cost = float(h.get('total_value') or 0)
            current = float(h.get('current_value') or 0)
            pnl_pct = ((current - cost) / cost * 100) if cost else 0.0
            pl_lines.append(f"- {ticker}: {pnl_pct:+.2f}% vs entry (stop loss -3%, take profit +5%)")
        except Exception:
            continue
    if pl_lines:
        pl_summary = "\n".join(pl_lines)
    else:
        pl_summary = "- No open positions"

    def _safe_format(template: str, values: Dict[str, Any]) -> str:
        """Safely format prompt templates that contain literal JSON braces."""
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

    # Use versioned prompt template
    user_prompt_values = {
        "available_cash": available_cash,
        "max_spendable": max_spendable,
        "min_buffer": MIN_BUFFER,
        "max_funds": total_portfolio_value,
        "holdings": holdings_text,
        "feedback": feedback_context,
        "summaries": summarized_text,
        "pnl_summary": pl_summary,
        "min_buy": f"{int(MIN_BUY_AMOUNT):,}",
        "typical_buy_low": f"{int(TYPICAL_BUY_LOW):,}",
        "typical_buy_high": f"{int(TYPICAL_BUY_HIGH):,}",
        "max_buy": f"{int(MAX_BUY_AMOUNT):,}",
        "buy_example": f"{int((TYPICAL_BUY_LOW + TYPICAL_BUY_HIGH) / 2):,}",
        "below_min_buy": f"{max(int(MIN_BUY_AMOUNT * 0.6), 100):,}",
        "well_below_min": f"{max(int(MIN_BUY_AMOUNT * 0.4), 100):,}",
        "max_trades": MAX_TRADES,
        "one_trade_mode": ONE_TRADE_MODE,
    }
    prompt = _safe_format(user_prompt_template, user_prompt_values)


    prompt_preview_limit = int(os.getenv("DAI_PROMPT_DEBUG_LIMIT", "2000"))
    prompt_snippet = prompt[:prompt_preview_limit]
    print(f"🧠 Decider prompt preview (showing {len(prompt_snippet)} of {len(prompt)} chars):\n{prompt_snippet}")
    if len(prompt_snippet) < len(prompt):
        print("… (prompt truncated for console preview)")
    
    # Build explicit list of required decisions for current holdings
    current_tickers = [h['ticker'] for h in stock_holdings] if stock_holdings else []
    
    # Show what AI is being told
    if current_tickers:
        print(f"💼 Current Holdings AI MUST Analyze: {', '.join(current_tickers)}")
    else:
        print(f"💼 Portfolio: NO positions (cash only)")
    
    # Create clear instructions with actual ticker examples
    holdings_instructions = ""
    if current_tickers:
        holdings_instructions = f"\n🚨 YOU CURRENTLY OWN: {', '.join(current_tickers)}\n"
        holdings_instructions += "For EACH of these stocks, you MUST decide: SELL (take profits/cut losses) or HOLD (keep position)\n"
    else:
        holdings_instructions = "\n✅ You have NO current positions - only consider new BUYS\n"
    
    example_buy_amount = int((TYPICAL_BUY_LOW + TYPICAL_BUY_HIGH) / 2)
    buy_range_display = f"${int(MIN_BUY_AMOUNT):,}-${int(MAX_BUY_AMOUNT):,}"

    prompt += holdings_instructions
    prompt += f"""\n
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 OUTPUT FORMAT: JSON ARRAY ONLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your response must be ONLY a JSON array of decisions. Nothing else.

Format:
[
  {{"action": "sell", "ticker": "TICKER", "amount_usd": 0, "reason": "why"}},
  {{"action": "hold", "ticker": "TICKER", "amount_usd": 0, "reason": "why"}},
  {{"action": "buy", "ticker": "TICKER", "amount_usd": ${example_buy_amount:,}, "reason": "why"}}
]

Rules:
- Provide SELL or HOLD for EVERY stock you own (listed above)
- Can suggest BUY for new stocks
- amount_usd: 0 for sell/hold, {buy_range_display} for buy

START YOUR JSON ARRAY NOW (begin with [ ):"""
    
    # Debug: Print first 300 chars of prompt
    print(f"📝 Prompt preview: {prompt[:300]}...")
    
    # Import the JSON schema for structured responses
    # Get AI decision regardless of market status
    ai_response = prompt_manager.ask_openai(
        prompt, 
        system_prompt, 
        agent_name="DeciderAgent"
    )
    
    # Ensure response is always a list
    if isinstance(ai_response, dict):
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

    # Guarantee a decision exists for every current holding
    existing_decisions = {}
    for decision in ai_response:
        if isinstance(decision, dict):
            ticker = (decision.get("ticker") or "").upper()
            if ticker:
                existing_decisions[ticker] = decision

    current_tickers = [h['ticker'].upper() for h in stock_holdings] if stock_holdings else []
    missing_tickers = [ticker for ticker in current_tickers if ticker not in existing_decisions]

    if missing_tickers:
        print(f"⚠️  AI omitted decisions for: {', '.join(missing_tickers)} — auto-filling HOLD entries.")
        for ticker in missing_tickers:
            ai_response.append({
                "action": "hold",
                "ticker": ticker,
                "amount_usd": 0,
                "reason": "Auto-generated HOLD because AI omitted this position. Provide explicit reasoning next cycle."
            })

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
    validator = DecisionValidator(stock_holdings, cash_balance)
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
                if action in ['buy', 'sell']:
                    original_reason = decision.get('reason', 'No reason provided')
                    # Only add prefix if not already present (avoid double prefix)
                    if not original_reason.startswith('⛔ MARKET CLOSED'):
                        decision['reason'] = f"⛔ MARKET CLOSED - No action taken. AI suggested: {original_reason}"
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
                if not market_open and extracted.get('action', '').lower() in ['buy', 'sell']:
                    original_reason = extracted.get('reason', '')
                    extracted['reason'] = f"⛔ MARKET CLOSED - No action taken. AI suggested: {original_reason}"
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
                if action in ['buy', 'sell']:
                    original_reason = extracted_from_full.get('reason', '')
                    extracted_from_full["reason"] = f"⛔ MARKET CLOSED - No action taken. AI suggested: {original_reason}"
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
        
        # Create a run_id based on the latest timestamp
        latest_timestamp = max(s['timestamp'] for s in unprocessed_summaries)
        run_id = latest_timestamp.strftime("%Y%m%dT%H%M%S")
        
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
        store_trade_decisions(decisions, run_id)
        
        # Execute trades through the unified trading interface
        try:
            from trading_interface import trading_interface
            execution_results = trading_interface.execute_trade_decisions(decisions)
            
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
            update_holdings(decisions)
        except Exception as e:
            print(f"❌ Error in trading interface: {e}")
            print("🔄 Falling back to simulation mode")
            update_holdings(decisions)
        
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
