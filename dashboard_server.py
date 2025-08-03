from flask import Flask, render_template, jsonify, request
from sqlalchemy import text
from config import engine
import json
import pandas as pd
import threading
import time
import yfinance as yf
from datetime import datetime

# Configuration
REFRESH_INTERVAL_MINUTES = 10
app = Flask(__name__)

def create_portfolio_history_table():
    """Create portfolio_history table to track portfolio value over time"""
    with engine.begin() as conn:
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

def record_portfolio_snapshot():
    """Record current portfolio state for historical tracking"""
    with engine.begin() as conn:
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

# Initialize portfolio history table
create_portfolio_history_table()


@app.route("/")
def dashboard():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, purchase_timestamp, current_timestamp,
                   total_value, current_value, gain_loss, reason
            FROM holdings
            WHERE is_active = TRUE
            ORDER BY CASE WHEN ticker = 'CASH' THEN 1 ELSE 0 END, ticker
        """)).fetchall()

        holdings = [dict(row._mapping) for row in result]

        # Calculate portfolio metrics
        cash_balance = next((h["current_value"] for h in holdings if h["ticker"] == "CASH"), 0)
        stock_holdings = [h for h in holdings if h["ticker"] != "CASH"]
        
        total_current_value = sum(h["current_value"] for h in stock_holdings)
        total_invested = sum(h["total_value"] for h in stock_holdings)
        total_profit_loss = sum(h["gain_loss"] for h in stock_holdings)
        total_portfolio_value = total_current_value + cash_balance
        
        # Calculate metrics relative to initial $10,000 investment
        initial_investment = 10000.0
        net_gain_loss = total_portfolio_value - initial_investment
        net_percentage_gain = (net_gain_loss / initial_investment * 100)
        
        # Calculate percentage gain on invested amount (excluding cash)
        percentage_gain = (total_profit_loss / total_invested * 100) if total_invested > 0 else 0

        return render_template("dashboard.html", active_tab="dashboard", holdings=holdings,
                               total_value=total_portfolio_value, cash_balance=cash_balance,
                               portfolio_value=total_current_value, total_invested=total_invested,
                               total_profit_loss=total_profit_loss, percentage_gain=percentage_gain,
                               initial_investment=initial_investment, net_gain_loss=net_gain_loss,
                               net_percentage_gain=net_percentage_gain)

@app.template_filter('from_json')
def from_json_filter(s):
    try:
        return json.loads(s)
    except Exception:
        return {}


@app.route("/trades")
def trade_decisions():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM trade_decisions 
            WHERE data::text NOT LIKE '%%Max retries reached%%'
              AND data::text NOT LIKE '%%API error, no response%%'
            ORDER BY id DESC LIMIT 20
        """)).fetchall()
        trades = [dict(row._mapping) for row in result]
        return render_template("trades.html", active_tab="trades", trades=trades)

@app.route("/summaries")
def summaries():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM summaries 
            WHERE data::text NOT LIKE '%%API error, no response%%'
            ORDER BY id DESC LIMIT 20
        """)).fetchall()

        summaries = []
        for row in result:
            try:
                outer = json.loads(row.data)
                summary_data = outer.get("summary")
                if isinstance(summary_data, str):
                    summary_data = json.loads(summary_data)

                summaries.append({
                    "agent": row.agent,
                    "timestamp": row.timestamp,
                    "headlines": summary_data.get("headlines", []),
                    "insights": summary_data.get("insights", "")
                })
            except Exception as e:
                print(f"Failed to parse summary row {row.id}: {e}")
                continue

        return render_template("summaries.html", summaries=summaries)

@app.route("/api/holdings")
def api_holdings():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM holdings WHERE is_active = TRUE
        """)).fetchall()
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/history")
def api_history():
    ticker = request.args.get("ticker")
    with engine.connect() as conn:
        if ticker:
            result = conn.execute(text("""
                SELECT current_price_timestamp, current_value FROM holdings
                WHERE ticker = :ticker ORDER BY current_price_timestamp ASC
            """), {"ticker": ticker}).fetchall()
        else:
            result = conn.execute(text("""
                SELECT current_timestamp, SUM(current_value) AS total_value
                FROM holdings
                GROUP BY current_timestamp ORDER BY current_timestamp ASC
            """)).fetchall()

        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/portfolio-history")
def api_portfolio_history():
    """Get portfolio performance over time"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, total_invested, 
                   total_profit_loss, percentage_gain, cash_balance
            FROM portfolio_history 
            ORDER BY timestamp ASC
        """)).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/portfolio-performance")
def api_portfolio_performance():
    """Get portfolio performance relative to initial $10,000 investment"""
    initial_investment = 10000.0
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, cash_balance,
                   (total_portfolio_value - :initial_investment) as net_gain_loss,
                   ((total_portfolio_value - :initial_investment) / :initial_investment * 100) as net_percentage_gain
            FROM portfolio_history 
            ORDER BY timestamp ASC
        """), {"initial_investment": initial_investment}).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/profit-loss")
def api_profit_loss():
    """Get current profit/loss breakdown by holding"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price,
                   total_value, current_value, gain_loss,
                   CASE 
                       WHEN total_value > 0 THEN (gain_loss / total_value * 100)
                       ELSE 0 
                   END as percentage_gain
            FROM holdings
            WHERE is_active = TRUE AND ticker != 'CASH'
            ORDER BY gain_loss DESC
        """)).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

def update_prices():
    while True:
        time.sleep(REFRESH_INTERVAL_MINUTES * 60)
        with engine.begin() as conn:
            result = conn.execute(text("SELECT ticker FROM holdings WHERE is_active = TRUE AND ticker != 'CASH'"))
            tickers = [row.ticker for row in result]
            for ticker in tickers:
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="1d")
                    if hist.empty:
                        print(f"{ticker}: No data found for this date range, symbol may be delisted")
                        continue

                    price = float(hist.iloc[-1].Close)
                    now = datetime.utcnow()

                    conn.execute(text("""
                        UPDATE holdings
                        SET current_price = :price,
                            current_value = shares * :price,
                            gain_loss = (shares * :price) - total_value,
                            current_price_timestamp = :current_price_timestamp
                        WHERE ticker = :ticker"""), {
                            "price": price,
                            "current_price_timestamp": now,
                            "ticker": ticker
                        })
                except Exception as e:
                    print(f"Failed to update {ticker}: {e}")
            
            # Record portfolio snapshot after price updates
            try:
                record_portfolio_snapshot()
                print("Portfolio snapshot recorded")
            except Exception as e:
                print(f"Failed to record portfolio snapshot: {e}")

def start_price_updater():
    thread = threading.Thread(target=update_prices, daemon=True)
    thread.start()

if __name__ == "__main__":
    start_price_updater()
    app.run(debug=True, port=5000)
