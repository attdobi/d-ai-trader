import json
import pytz
from datetime import datetime
import time
from math import floor
import concurrent.futures
from sqlalchemy import text
from config import engine, PromptManager, session, openai, get_current_config_hash, get_trading_mode
import yfinance as yf
from feedback_agent import TradeOutcomeTracker

# Timezone configuration
PACIFIC_TIMEZONE = pytz.timezone('US/Pacific')
EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

# Trading configuration
MAX_TRADES = 5
MAX_FUNDS = 10000
MIN_BUFFER = 100  # Must always have at least this much left

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

# Initialize feedback tracker
feedback_tracker = TradeOutcomeTracker()

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
        stock = yf.Ticker(clean_ticker)

        # Method 1: Try to get current price from info (works during market hours)
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Submit the task with a 10 second timeout
                future = executor.submit(lambda: stock.info.get('currentPrice'))
                try:
                    current_price = future.result(timeout=10)
                    if current_price and current_price > 0:
                        print(f"✅ {clean_ticker}: Got current price from info: ${current_price:.2f}")
                        return float(current_price)
                except concurrent.futures.TimeoutError:
                    print(f"⏰ {clean_ticker}: Price fetch timeout after 10 seconds")
                    raise Exception("Timeout fetching price")
                
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 1 failed: {e}")

        # Method 2: Try regular market price from info
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Submit the task with a 10 second timeout
                future = executor.submit(lambda: stock.info.get('regularMarketPrice'))
                try:
                    regular_price = future.result(timeout=10)
                    if regular_price and regular_price > 0:
                        print(f"✅ {clean_ticker}: Got regular market price: ${regular_price:.2f}")
                        return float(regular_price)
                except concurrent.futures.TimeoutError:
                    print(f"⏰ {clean_ticker}: Regular market price timeout after 10 seconds")
                    raise Exception("Timeout fetching regular market price")
                
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 2 failed: {e}")

        # Method 3: Try previous close from info (works after hours)
        try:
            prev_close = stock.info.get('previousClose')
            if prev_close and prev_close > 0:
                print(f"✅ {clean_ticker}: Got previous close: ${prev_close:.2f}")
                return float(prev_close)
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 3 failed: {e}")

        # Method 3b: Try fast_info fields (often available off-hours)
        try:
            fast_info = getattr(stock, 'fast_info', None)
            if fast_info:
                for key in (
                    'lastPrice',
                    'regularMarketPreviousClose',
                    'regularMarketPrice',
                ):
                    value = None
                    try:
                        value = fast_info.get(key) if hasattr(fast_info, 'get') else getattr(fast_info, key, None)
                    except Exception:
                        value = None
                    if value and float(value) > 0:
                        print(f"✅ {clean_ticker}: Got price from fast_info {key}: ${float(value):.2f}")
                        return float(value)
        except Exception as e:
            print(f"⚠️  {clean_ticker}: fast_info lookup failed: {e}")

        # Method 4: Try history with 1 day period
        try:
            hist = stock.history(period="1d", interval="1d", prepost=True)
            if hist is not None and len(hist) > 0 and 'Close' in hist.columns:
                price = float(hist['Close'].dropna().iloc[-1])
                print(f"✅ {clean_ticker}: Got price from 1d history: ${price:.2f}")
                return price
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 4 failed: {e}")

        # Method 5: Try history with 5 day period
        try:
            hist = stock.history(period="5d", interval="1d", prepost=True)
            if hist is not None and len(hist) > 0 and 'Close' in hist.columns:
                price = float(hist['Close'].dropna().iloc[-1])
                print(f"✅ {clean_ticker}: Got price from 5d history: ${price:.2f}")
                return price
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 5 failed: {e}")

        # Method 6: Try specific date range (last 7 days)
        try:
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            hist = stock.history(start=start_date, end=end_date, interval="1d", prepost=True)
            if hist is not None and len(hist) > 0 and 'Close' in hist.columns:
                price = float(hist['Close'].dropna().iloc[-1])
                print(f"✅ {clean_ticker}: Got price from 7d history: ${price:.2f}")
                return price
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 6 failed: {e}")

        # Method 7: Use yf.download over a month and pick last valid close (reliable on weekends)
        try:
            dl = yf.download(
                tickers=clean_ticker,
                period="1mo",
                interval="1d",
                prepost=True,
                progress=False,
            )
            if dl is not None and len(dl) > 0:
                close_series = dl['Close'] if 'Close' in dl.columns else dl.get(('Close', clean_ticker))
                if close_series is not None:
                    last_valid = close_series.dropna()
                    if len(last_valid) > 0:
                        price = float(last_valid.iloc[-1])
                        print(f"✅ {clean_ticker}: Got price from yf.download 1mo: ${price:.2f}")
                        return price
        except Exception as e:
            print(f"⚠️  {clean_ticker}: Method 7 failed: {e}")

        # If all attempts fail, do not use fallback prices - skip trading instead
        print(f"❌ All price fetching methods failed for {clean_ticker} (original: {ticker})")
        print(f"💡 This may be due to:")
        print(f"   - After market hours or weekend/holiday")
        print(f"   - Temporary Yahoo Finance API issues/rate limits")
        print(f"   - Symbol may be invalid or delisted")
        print(f"🚫 Yahoo Finance rate limit exceeded - skipping trade to ensure accurate pricing")
        print(f"💡 API rate limits typically clear within 1 hour")
        
        return None

    except Exception as e:
        print(f"❌ Failed to fetch price for {clean_ticker} (original: {ticker}): {e}")
        return None

def execute_real_world_trade(decision):
    """Execute a real trade through Schwab API when in real_world mode"""
    trading_mode = get_trading_mode()
    
    if trading_mode != "real_world":
        return True  # Skip real execution in simulation mode
    
    try:
        # Import trading interface (only when needed)
        from trading_interface import trading_interface
        
        action = decision.get('action', '').lower()
        ticker = decision.get('ticker', '')
        amount_usd = decision.get('amount_usd', 0)
        
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
        else:
            return True  # Hold decisions don't require real execution
        
        if result.get('success'):
            print(f"💰 REAL TRADE EXECUTED: {action.upper()} {ticker} for ${amount_usd}")
            return True
        else:
            print(f"❌ REAL TRADE FAILED: {action.upper()} {ticker} - {result.get('error', 'Unknown error')}")
            return False
            
    except ImportError:
        print("⚠️  Trading interface not available for real-world trading")
        print("🔄 Falling back to simulation mode for this trade")
        return True
    except Exception as e:
        print(f"❌ Real trade execution error: {e}")
        return False

def update_holdings(decisions):
    # Use Pacific time converted to UTC for consistency
    pacific_now = datetime.now(PACIFIC_TIMEZONE)
    timestamp = pacific_now.astimezone(pytz.UTC).replace(tzinfo=None)
    skipped_decisions = []
    trading_mode = get_trading_mode()
    config_hash = get_current_config_hash()
    
    print(f"🔄 Updating holdings in {trading_mode.upper()} mode (config: {config_hash})")
    
    # Execute real trades if in real_world mode
    if trading_mode == "real_world":
        print("💰 Executing real trades through Schwab API...")
        for decision in decisions:
            if decision.get('action', '').lower() in ['buy', 'sell']:
                success = execute_real_world_trade(decision)
                if not success:
                    print(f"⚠️  Real trade failed for {decision.get('ticker', 'unknown')}, continuing with simulation")
    else:
        print("🎮 Running in simulation mode - no real trades executed")

    # Normalize decisions
    decisions_normalized = [
        {
            **d,
            "action": (d.get("action") or "").lower(),
        }
        for d in decisions
    ]
    
    # Separate decision types
    sell_decisions = [d for d in decisions_normalized if d.get("action") == "sell"]
    buy_decisions = [d for d in decisions_normalized if d.get("action") == "buy"]  # Keep original order for priority
    hold_decisions = [d for d in decisions_normalized if d.get("action") not in ("buy", "sell")]
    
    print(f"📊 Processing {len(sell_decisions)} sells, {len(buy_decisions)} buys, {len(hold_decisions)} holds")
    
    # Get current cash balance
    with engine.begin() as conn:
        cash_row = conn.execute(text("SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash}).fetchone()
        available_cash = float(cash_row.current_value) if cash_row else MAX_FUNDS
        print(f"💰 Starting cash balance: ${available_cash:.2f}")

    # 1) EXECUTE ALL SELLS FIRST (to free up cash)
    if sell_decisions:
        print(f"🔥 Executing {len(sell_decisions)} sell orders first...")
        available_cash = process_sell_decisions(sell_decisions, available_cash, timestamp, config_hash, skipped_decisions)
    
    # Wait 30 seconds between sells and buys if both exist (allows position swapping)
    if sell_decisions and buy_decisions:
        print("⏳ Waiting 30 seconds after sells to allow funds to clear before buys...")
        import time
        time.sleep(30)
    
    # 2) EXECUTE BUYS IN ORDER UNTIL CASH RUNS OUT  
    if buy_decisions:
        print(f"💸 Executing buy orders with ${available_cash:.2f} available...")
        available_cash = process_buy_decisions(buy_decisions, available_cash, timestamp, config_hash, skipped_decisions)
    
    # 3) Log hold decisions
    if hold_decisions:
        print(f"⏸️  {len(hold_decisions)} hold decisions (no action needed)")
        for decision in hold_decisions:
            skipped_decisions.append({
                **decision,
                "reason": f"Hold decision - no action taken (Original: {decision.get('reason', '')})"
            })

    return skipped_decisions

def process_sell_decisions(sell_decisions, available_cash, timestamp, config_hash, skipped_decisions):
    """Process all sell decisions and return updated cash balance"""
    
    # Track the cash we're adding from sells
    cash_from_sells = 0.0
    
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
                print(f"Market closed - recording sell decision for {ticker} but deferring execution.")
                skipped_decisions.append({
                    "action": "sell",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Market closed - execution deferred (Price: ${price:.2f}) (Original: {reason})"
                })
                continue

            holding = conn.execute(
                text("SELECT shares, purchase_price, purchase_timestamp, reason FROM holdings WHERE ticker = :ticker AND config_hash = :config_hash AND is_active = TRUE AND shares > 0"),
                {"ticker": clean_ticker, "config_hash": config_hash}
            ).fetchone()
            if holding:
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

def process_buy_decisions(buy_decisions, available_cash, timestamp, config_hash, skipped_decisions):
    if buy_decisions:
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
                    print(f"Skipping buy for {ticker} - market is closed.")
                    skipped_decisions.append({
                        "action": "buy",
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Market closed - no trade executed (Original: {reason})"
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

def process_buy_decisions(buy_decisions, available_cash, timestamp, config_hash, skipped_decisions):
    """Process all buy decisions and return updated cash balance"""
    
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
                print(f"Market closed - recording buy decision for {ticker} but deferring execution.")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Market closed - execution deferred (Price: ${price:.2f}) (Original: {reason})"
                })
                continue

            from math import floor
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
            if available_cash - actual_spent < MIN_BUFFER:
                print(f"Skipping buy for {ticker} - would exceed budget (need ${actual_spent:.2f}, available ${available_cash:.2f})")
                skipped_decisions.append({
                    "action": "buy",
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Budget exceeded - no trade executed (Original: {reason})"
                })
                continue

            # Execute real-world trade if in real_world mode
            real_trade_success = execute_real_world_trade(decision)

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
        print(f"🔧 Using DeciderAgent prompt v{prompt_version}")
    except Exception as e:
        print(f"⚠️  Could not load versioned prompt: {e}, using fallback")
        # Fallback to basic prompt
        system_prompt = "You are a day trading assistant making quick decisions based on current market news and momentum."
        user_prompt_template = """Based on the market analysis below, make specific trading decisions.

Current Portfolio:
- Available Cash: ${available_cash}
- Holdings: {holdings}

Market Analysis:
{summaries}

Make 1-3 specific trades. Return a JSON array with:
- "action": "buy" or "sell" or "hold"
- "ticker": Stock symbol
- "amount_usd": Dollar amount to trade
- "reason": Brief explanation"""
    
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
                except:
                    # If it's not JSON, treat it as plain text
                    summary_content = {'headlines': [], 'insights': summary_content}
            
            # Truncate long insights to reduce token usage
            insights = summary_content.get('insights', '')
            if len(insights) > 500:  # Limit insights to 500 characters
                insights = insights[:500] + "... [truncated]"
            
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
    summary_parts = []
    for s in parsed_summaries:
        headlines_text = ', '.join(s['headlines'][:3])  # Limit to 3 headlines per agent
        insights_text = s['insights'][:200] if len(s['insights']) > 200 else s['insights']  # Limit insights
        summary_parts.append(f"{s['agent']}: {headlines_text} | {insights_text}")
    
    summarized_text = "\n".join(summary_parts)

    # Separate cash and stock holdings
    cash_balance = next((h['current_value'] for h in holdings if h['ticker'] == 'CASH'), 0)
    stock_holdings = [h for h in holdings if h['ticker'] != 'CASH']
    
    holdings_text = "\n".join([
        f"{h['ticker']}: {h['shares']} shares at ${h['purchase_price']} → Current: ${h['current_price']} (Gain/Loss: ${h['gain_loss']:.2f}) (Reason: {h['reason']})"
        for h in stock_holdings
    ]) or "No current stock holdings."
    
    # Calculate available funds
    available_cash = cash_balance
    max_spendable = max(0, available_cash - MIN_BUFFER)

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

    # Use versioned prompt template
    prompt = user_prompt_template.format(
        available_cash=available_cash,
        max_spendable=max_spendable,
        min_buffer=MIN_BUFFER,
        max_funds=MAX_FUNDS,
        holdings=holdings_text,
        feedback=feedback_context,
        summaries=summarized_text
    )
    
    # Import the JSON schema for structured responses
    # Get AI decision regardless of market status
    ai_response = prompt_manager.ask_openai(
        prompt, 
        system_prompt, 
        agent_name="DeciderAgent"
    )
    
    # Ensure response is always a list
    if isinstance(ai_response, dict):
        ai_response = [ai_response]
    elif not isinstance(ai_response, list):
        print(f"⚠️  Unexpected response type: {type(ai_response)}, converting to list")
        ai_response = [ai_response] if ai_response else []
    
    # If market is closed, modify decisions to show they're deferred
    if not market_open:
        print("🕒 Market closed - Decisions recorded but execution deferred")
        # Modify each decision to indicate deferred execution
        for decision in ai_response:
            if isinstance(decision, dict) and decision.get('action') not in ['N/A', 'hold']:
                original_reason = decision.get('reason', '')
                decision['reason'] = f"Market closed - execution deferred. Original: {original_reason}"
                decision['execution_status'] = 'deferred'
    
    return ai_response

def extract_decision_info_from_text(text_content):
    """Try to extract decision info from malformed text responses"""
    import re
    
    # Look for common patterns like "buy AAPL", "sell TSLA", etc.
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
    
    # Filter out error responses before storing
    valid_decisions = []
    for decision in decisions:
        if isinstance(decision, dict) and 'error' in decision:
            print(f"⚠️  Skipping error response: {decision.get('error', 'Unknown error')}")
            continue
        if isinstance(decision, dict) and decision.get('action') and decision.get('ticker'):
            valid_decisions.append(decision)
        else:
            print(f"⚠️  Invalid decision format: {decision}")
            # Try to extract info from malformed decision
            extracted = extract_decision_info_from_text(decision)
            if extracted:
                print(f"✅ Extracted: {extracted}")
                valid_decisions.append(extracted)
    
    # Only store if we have valid decisions
    if not valid_decisions:
        print("❌ No valid trade decisions to store - AI response was malformed")
        # Try to extract info from the entire response text
        print(f"📋 Attempting to extract from full response: {decisions}")
        extracted_from_full = extract_decision_info_from_text(str(decisions))
        
        if extracted_from_full:
            print(f"✅ Extracted from full response: {extracted_from_full}")
            # If market is closed, modify the reason
            if not is_market_open():
                extracted_from_full["reason"] = f"Market closed - execution deferred. {extracted_from_full['reason']}"
            valid_decisions = [extracted_from_full]
        else:
            # Absolute fallback
            fallback_decision = {
                "action": "hold",
                "ticker": "SPY",  # Use SPY instead of UNKNOWN
                "amount_usd": 0,
                "reason": "AI response was completely unparseable - defaulting to hold SPY"
            }
            
            if not is_market_open():
                fallback_decision["reason"] = "Market is closed - no trading action taken (AI response was unparseable)"
            
            valid_decisions = [fallback_decision]
    
    # Get current Pacific time and convert to UTC for storage
    pacific_now = datetime.now(PACIFIC_TIMEZONE)
    utc_timestamp = pacific_now.astimezone(pytz.UTC).replace(tzinfo=None)
    
    print(f"🕐 Storing timestamp: {pacific_now.strftime('%Y-%m-%d %H:%M:%S %Z')} → {utc_timestamp} UTC")
    
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
            "timestamp": utc_timestamp,
            "data": json.dumps(valid_decisions),
            "config_hash": get_current_config_hash()
        })

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
