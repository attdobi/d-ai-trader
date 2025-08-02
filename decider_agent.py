import json
from datetime import datetime
from math import floor
from sqlalchemy import text
from config import engine, PromptManager, session, openai
import yfinance as yf

# Trading configuration
MAX_TRADES = 5
MAX_FUNDS = 10000
MIN_BUFFER = 100  # Must always have at least this much left

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

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
                continue

            if action == "buy":
                shares = floor(amount / price)
                if shares == 0:
                    print(f"Skipping buy for {ticker} due to insufficient funds for 1 share.")
                    continue
                actual_spent = shares * price
                if cash - actual_spent < MIN_BUFFER:
                    print(f"Skipping buy for {ticker}, would breach minimum buffer.")
                    continue

                conn.execute(text("""
                    INSERT INTO holdings (ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                    VALUES (:ticker, :shares, :purchase_price, :current_price, :purchase_timestamp, :current_price_timestamp, :total_value, :current_value, :gain_loss, :reason, TRUE)
                    ON CONFLICT (ticker) DO UPDATE SET
                        shares = EXCLUDED.shares,
                        purchase_price = EXCLUDED.purchase_price,
                        current_price = EXCLUDED.current_price,
                        purchase_timestamp = EXCLUDED.purchase_timestamp,
                        current_price_timestamp = EXCLUDED.current_price_timestamp,
                        total_value = EXCLUDED.total_value,
                        current_value = EXCLUDED.current_value,
                        gain_loss = EXCLUDED.gain_loss,
                        reason = EXCLUDED.reason,
                        is_active = TRUE
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

                cash -= actual_spent

            elif action == "sell":
                holding = conn.execute(text("SELECT shares, purchase_price FROM holdings WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()
                if holding:
                    shares = float(holding.shares)
                    purchase_price = float(holding.purchase_price)
                    total_value = shares * price
                    purchase_value = shares * purchase_price
                    gain_loss = total_value - purchase_value

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

def ask_decision_agent(summaries, run_id, holdings):
    parsed_summaries = []
    for s in summaries:
        try:
            parsed = json.loads(s['data']) if isinstance(s['data'], str) else s['data']
            parsed_summaries.append({
                "agent": s['agent'],
                "headlines": parsed.get('summary', {}).get('headlines', []),
                "insights": parsed.get('summary', {}).get('insights', '')
            })
        except Exception as e:
            print(f"Failed to parse summary for agent {s['agent']}: {e}")

    summarized_text = "\n\n".join([
        f"Agent: {s['agent']}\nHeadlines: {', '.join(s['headlines'])}\nInsights: {s['insights']}"
        for s in parsed_summaries
    ])

    holdings_text = "\n".join([
        f"{h['ticker']}: {h['shares']} shares at ${h['purchase_price']} (Reason: {h['reason']})"
        for h in holdings if h['ticker'] != 'CASH'
    ]) or "No current holdings."

    prompt = f"""
You are a financial decision-making AI tasked with determining a set of buy/sell recommendations based on the following summaries and current portfolio.
Use a one-month outlook, trying to maximize ROI. Do not exceed {MAX_TRADES} total trades, and never allocate more than ${MAX_FUNDS - MIN_BUFFER} total.
Retain at least ${MIN_BUFFER} in funds. Feedback is unavailable for this run.
Remember in some cases a new story and image could be shown for market manipulation. 
Though it is good to buy on optimism and sell on negative news it could also be a good time to sell and buy, respectively.

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

    system_prompt = "You are a trading advisor providing rational investment actions."
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
    run_id = get_latest_run_id()
    if not run_id:
        print("No summaries found.")
    else:
        summaries = fetch_summaries(run_id)
        holdings = fetch_holdings()
        decisions = ask_decision_agent(summaries, run_id, holdings)
        store_trade_decisions(decisions, run_id)
        update_holdings(decisions)
        print(f"Stored decisions and updated holdings for run {run_id}")
