from flask import Flask, render_template, jsonify, request
from sqlalchemy import text
from config import engine
import json
import pandas as pd
import threading
import time
import yfinance as yf

# Configuration
REFRESH_INTERVAL_MINUTES = 10
app = Flask(__name__)


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

        total_portfolio_value = sum(h["current_value"] for h in holdings if h["ticker"] != "CASH")
        cash_balance = next((h["current_value"] for h in holdings if h["ticker"] == "CASH"), 0)
        total_value = total_portfolio_value + cash_balance

        return render_template("dashboard.html", active_tab="dashboard", holdings=holdings,
                               total_value=total_value, cash_balance=cash_balance,
                               portfolio_value=total_portfolio_value)

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
                            gain_loss = (shares * :price) - total_value ## This is wrong.
                            current_price_timestamp = :current_price_timestamp
                        WHERE ticker = :ticker"""), {
                            "price": price,
                            "current_price_timestamp": now,
                            "ticker": ticker
                        })
                except Exception as e:
                    print(f"Failed to update {ticker}: {e}")

def start_price_updater():
    thread = threading.Thread(target=update_prices, daemon=True)
    thread.start()

if __name__ == "__main__":
    start_price_updater()
    app.run(debug=True, port=5000)
