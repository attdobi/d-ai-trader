import json
from datetime import datetime
from math import floor
from sqlalchemy import text
from config import engine, PromptManager, session, openai
import yfinance as yf
from feedback_agent import TradeOutcomeTracker

# Trading configuration
MAX_TRADES = 5
MAX_FUNDS = 10000
MIN_BUFFER = 100  # Must always have at least this much left

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

# Initialize feedback tracker
feedback_tracker = TradeOutcomeTracker()

def get_latest_run_id():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT run_id FROM summaries
            ORDER BY timestamp DESC LIMIT 1
        """)).fetchone()
        return result[0] if result else None

def fetch_summaries(run_id):
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT agent, data FROM summaries
            WHERE run_id = :run_id
        """), {"run_id": run_id})
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
            conn.execute(text("""
                INSERT INTO processed_summaries (summary_id, processed_by, run_id)
                VALUES (:summary_id, 'decider', :run_id)
            """), {
                "summary_id": summary_id,
                "run_id": datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            })

def fetch_holdings():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS holdings (
                ticker TEXT PRIMARY KEY,
                shares FLOAT,
                purchase_price FLOAT,
                current_price FLOAT,
                purchase_timestamp TIMESTAMP,
                current_price_timestamp TIMESTAMP,
                total_value FLOAT,
                current_value FLOAT,
                gain_loss FLOAT,
                reason TEXT,
                is_active BOOLEAN
            )
        """))

        # Ensure cash row exists
        result = conn.execute(text("SELECT 1 FROM holdings WHERE ticker = 'CASH'"))
        if not result.fetchone():
            conn.execute(text("""
                INSERT INTO holdings (ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                VALUES ('CASH', 1, :initial_cash, :initial_cash, now(), now(), :initial_cash, :initial_cash, 0, 'Initial cash', TRUE)
            """), {"initial_cash": MAX_FUNDS})

        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, total_value, current_value, gain_loss, reason, is_active FROM holdings
            WHERE is_active = TRUE
        """))
        return [row._mapping for row in result]

def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        return float(stock.history(period="1d").iloc[-1].Close)
    except Exception as e:
        print(f"Failed to fetch price for {ticker}: {e}")
        return None

def update_holdings(decisions):
    timestamp = datetime.utcnow()
    skipped_decisions = []  # Track decisions that were skipped
    
    with engine.begin() as conn:
        # Get current cash balance
        cash_row = conn.execute(text("SELECT current_value FROM holdings WHERE ticker = 'CASH'")).fetchone()
        cash = float(cash_row.current_value) if cash_row else MAX_FUNDS

        for decision in decisions:
            action = decision.get("action")
            ticker = decision.get("ticker")
            amount = float(decision.get("amount_usd", 0))
            reason = decision.get("reason", "")

            price = get_current_price(ticker)
            if not price:
                print(f"Skipping {action} for {ticker} due to missing price.")
                # Record the skipped decision
                skipped_decision = {
                    "action": action,
                    "ticker": ticker,
                    "amount_usd": amount,
                    "reason": f"Market closed - no trade executed (Original: {reason})"
                }
                skipped_decisions.append(skipped_decision)
                continue

            if action == "buy":
                shares = floor(amount / price)
                if shares == 0:
                    print(f"Skipping buy for {ticker} due to insufficient funds for 1 share.")
                    # Record the skipped decision
                    skipped_decision = {
                        "action": action,
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Insufficient funds for 1 share - no trade executed (Original: {reason})"
                    }
                    skipped_decisions.append(skipped_decision)
                    continue
                actual_spent = shares * price
                if cash - actual_spent < MIN_BUFFER:
                    print(f"Skipping buy for {ticker}, would breach minimum buffer.")
                    # Record the skipped decision
                    skipped_decision = {
                        "action": action,
                        "ticker": ticker,
                        "amount_usd": amount,
                        "reason": f"Would breach minimum buffer - no trade executed (Original: {reason})"
                    }
                    skipped_decisions.append(skipped_decision)
                    continue

                # Check if we already have this ticker (active or inactive)
                existing = conn.execute(text("SELECT shares, total_value, gain_loss, is_active, reason FROM holdings WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()
                
                if existing:
                    if existing.is_active:
                        # Accumulate shares and total investment (cost basis)
                        new_shares = float(existing.shares) + shares
                        new_total_value = float(existing.total_value) + actual_spent
                        new_current_value = new_shares * price
                        # Preserve any existing unrealized gains/losses and add this purchase at cost
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
                            WHERE ticker = :ticker
                        """), {
                            "ticker": ticker,
                            "shares": new_shares,
                            "avg_price": new_avg_price,
                            "current_price": float(price),
                            "timestamp": timestamp,
                            "total_value": new_total_value,
                            "current_value": new_current_value,
                            "gain_loss": new_gain_loss,
                            "reason": f"{existing.reason if existing.reason else ''} + {reason}"
                        })
                        print(f"Added {shares} shares of {ticker}. Total: {new_shares} shares, Avg cost: ${new_avg_price:.2f}")
                    else:
                        # Reactivate the holding with new shares
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
                            WHERE ticker = :ticker
                        """), {
                            "ticker": ticker,
                            "shares": float(shares),
                            "purchase_price": float(price),
                            "current_price": float(price),
                            "timestamp": timestamp,
                            "total_value": float(shares * price),
                            "current_value": float(shares * price),
                            "gain_loss": 0.0,
                            "reason": reason
                        })
                        print(f"Reactivated {ticker}: {shares} shares at ${price:.2f}")
                else:
                    # First purchase of this ticker
                    conn.execute(text("""
                        INSERT INTO holdings (ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                        VALUES (:ticker, :shares, :purchase_price, :current_price, :purchase_timestamp, :current_price_timestamp, :total_value, :current_value, :gain_loss, :reason, TRUE)
                    """), {
                        "ticker": ticker,
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
                    print(f"First purchase: {shares} shares of {ticker} at ${price:.2f}")

                cash -= actual_spent

            elif action == "sell":
                holding = conn.execute(text("SELECT shares, purchase_price, purchase_timestamp, reason FROM holdings WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()
                if holding:
                    shares = float(holding.shares)
                    purchase_price = float(holding.purchase_price)
                    total_value = shares * price
                    purchase_value = shares * purchase_price
                    gain_loss = total_value - purchase_value

                    # Record outcome for feedback system
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
                        WHERE ticker = :ticker
                    """), {
                        "ticker": ticker,
                        "price": float(price),
                        "timestamp": timestamp,
                        "value": total_value,
                        "gain_loss": gain_loss
                    })

                    cash += total_value

        # Update cash balance
        conn.execute(text("""
            UPDATE holdings SET
                current_price = :cash,
                current_value = :cash,
                total_value = :cash,
                current_price_timestamp = :timestamp
            WHERE ticker = 'CASH'
        """), {"cash": cash, "timestamp": timestamp})
    
    # Store skipped decisions if any
    if skipped_decisions:
        run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        store_trade_decisions(skipped_decisions, f"{run_id}_skipped")
        print(f"Stored {len(skipped_decisions)} skipped decisions due to market closure")

def record_portfolio_snapshot():
    """Record current portfolio state for historical tracking - same as dashboard_server"""
    with engine.begin() as conn:
        # Ensure portfolio_history table exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id SERIAL PRIMARY KEY,
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

    holdings_text = "\n".join([
        f"{h['ticker']}: {h['shares']} shares at ${h['purchase_price']} (Reason: {h['reason']})"
        for h in holdings if h['ticker'] != 'CASH'
    ]) or "No current holdings."

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

    prompt = f"""
You are a financial decision-making AI. Make buy/sell recommendations based on the summaries and current portfolio.
Use a one-month outlook, maximize ROI. Do not exceed {MAX_TRADES} total trades, never allocate more than ${MAX_FUNDS - MIN_BUFFER} total.
Retain at least ${MIN_BUFFER} in funds.

Performance Context: {feedback_context}

Summaries:
{summarized_text}

Current Holdings:
{holdings_text}

Return a JSON list of trade decisions. Each decision should include:
- action ("buy" or "sell")
- ticker
- amount_usd (funds to allocate or recover)
- reason (short term, long term, etc)
Respond strictly in valid JSON format with keys.
"""

    system_prompt = "You are a trading advisor providing rational investment actions. Learn from past performance feedback to improve decisions."
    return prompt_manager.ask_openai(prompt, system_prompt, agent_name="DeciderAgent")

def store_trade_decisions(decisions, run_id):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trade_decisions (
                id SERIAL PRIMARY KEY,
                run_id TEXT,
                timestamp TIMESTAMP,
                data JSONB
            )
        """))
        conn.execute(text("""
            INSERT INTO trade_decisions (run_id, timestamp, data) VALUES (:run_id, :timestamp, :data)
        """), {
            "run_id": run_id,
            "timestamp": datetime.utcnow(),
            "data": json.dumps(decisions)
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
    else:
        print(f"Found {len(unprocessed_summaries)} unprocessed summaries")
        
        # Create a run_id based on the latest timestamp
        latest_timestamp = max(s['timestamp'] for s in unprocessed_summaries)
        run_id = latest_timestamp.strftime("%Y%m%dT%H%M%S")
        
        holdings = fetch_holdings()
        decisions = ask_decision_agent(unprocessed_summaries, run_id, holdings)
        store_trade_decisions(decisions, run_id)
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
