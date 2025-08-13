from flask import Flask, render_template, jsonify, request
from sqlalchemy import text
from config import engine, get_gpt_model, get_prompt_version_config, get_trading_mode, get_current_config_hash
import json
import pandas as pd
import threading
import time
import yfinance as yf
from datetime import datetime
from feedback_agent import TradeOutcomeTracker
import subprocess
import sys
import os

# Configuration
REFRESH_INTERVAL_MINUTES = 10
app = Flask(__name__)

# Initialize trading interface for Schwab integration
try:
    from trading_interface import trading_interface
    SCHWAB_ENABLED = True
except ImportError:
    SCHWAB_ENABLED = False
    print("Warning: Trading interface not available, Schwab features disabled")

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
                holdings_snapshot JSONB,
                config_hash VARCHAR(50)
            )
        """))

def record_portfolio_snapshot():
    """Record current portfolio state for historical tracking"""
    config_hash = get_current_config_hash()
    with engine.begin() as conn:
        # Get current holdings
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, 
                   total_value, current_value, gain_loss
            FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchall()
        
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
             total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
            VALUES (:total_portfolio_value, :cash_balance, :total_invested, 
                    :total_profit_loss, :percentage_gain, :holdings_snapshot, :config_hash)
        """), {
            "total_portfolio_value": total_portfolio_value,
            "cash_balance": cash_balance,
            "total_invested": total_invested,
            "total_profit_loss": total_profit_loss,
            "percentage_gain": percentage_gain,
            "holdings_snapshot": json.dumps(holdings),
            "config_hash": config_hash
        })

# Initialize portfolio history table
create_portfolio_history_table()


@app.route("/")
def dashboard():
    # Import and ensure portfolio initialization
    from decider_agent import fetch_holdings
    
    # This will trigger initialization if needed
    holdings_data = fetch_holdings()
    
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, purchase_timestamp, current_timestamp,
                   total_value, current_value, gain_loss, reason
            FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
            ORDER BY CASE WHEN ticker = 'CASH' THEN 1 ELSE 0 END, ticker
        """), {"config_hash": config_hash}).fetchall()

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

        # Get current system configuration
        current_config = {
            'gpt_model': get_gpt_model(),
            'prompt_config': get_prompt_version_config(),
            'trading_mode': get_trading_mode(),
            'config_hash': get_current_config_hash()
        }

        return render_template("dashboard.html", active_tab="dashboard", holdings=holdings,
                               total_value=total_portfolio_value, cash_balance=cash_balance,
                               portfolio_value=total_current_value, total_invested=total_invested,
                               total_profit_loss=total_profit_loss, percentage_gain=percentage_gain,
                               initial_investment=initial_investment, net_gain_loss=net_gain_loss,
                               net_percentage_gain=net_percentage_gain, current_config=current_config)

@app.template_filter('from_json')
def from_json_filter(s):
    try:
        return json.loads(s)
    except Exception:
        return {}


@app.route("/trades")
def trade_decisions():
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM trade_decisions 
            WHERE config_hash = :config_hash
              AND data::text NOT LIKE '%%Max retries reached%%'
              AND data::text NOT LIKE '%%API error, no response%%'
              AND data::text NOT LIKE '%%"action": "N/A"%%'
            ORDER BY id DESC LIMIT 20
        """), {"config_hash": config_hash}).fetchall()
        
        trades = []
        for row in result:
            trade_dict = dict(row._mapping)
            
            # Parse JSON if data is a string
            if isinstance(trade_dict['data'], str):
                try:
                    parsed_data = json.loads(trade_dict['data'])
                    trade_dict['data'] = parsed_data
                except json.JSONDecodeError:
                    # If JSON parsing fails, create empty list
                    trade_dict['data'] = []
            
            # Ensure data is a list and each item is a dict
            if not isinstance(trade_dict['data'], list):
                trade_dict['data'] = []
            else:
                # Clean up each decision to ensure it's a dict with proper fields
                cleaned_data = []
                for decision in trade_dict['data']:
                    if isinstance(decision, dict):
                        # Ensure all required fields exist
                        cleaned_decision = {
                            'ticker': decision.get('ticker', 'N/A'),
                            'action': decision.get('action', 'N/A'),
                            'amount_usd': decision.get('amount_usd', 0),
                            'reason': decision.get('reason', 'N/A')
                        }
                        cleaned_data.append(cleaned_decision)
                    elif isinstance(decision, str):
                        # If decision is a string, try to parse it
                        try:
                            parsed_decision = json.loads(decision)
                            if isinstance(parsed_decision, dict):
                                cleaned_decision = {
                                    'ticker': parsed_decision.get('ticker', 'N/A'),
                                    'action': parsed_decision.get('action', 'N/A'),
                                    'amount_usd': parsed_decision.get('amount_usd', 0),
                                    'reason': parsed_decision.get('reason', 'N/A')
                                }
                                cleaned_data.append(cleaned_decision)
                        except:
                            # If parsing fails, skip this decision
                            continue
                
                trade_dict['data'] = cleaned_data
            
            trades.append(trade_dict)
        
        return render_template("trades.html", active_tab="trades", trades=trades)

@app.route("/summaries")
def summaries():
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM summaries 
            WHERE config_hash = :config_hash
              AND data::text NOT LIKE '%%API error, no response%%'
            ORDER BY id DESC LIMIT 20
        """), {"config_hash": config_hash}).fetchall()

        summaries = []
        for row in result:
            try:
                # Parse the outer JSON structure
                outer = json.loads(row.data)
                summary_data = outer.get("summary", {})
                
                # Handle case where summary_data might be a string or dict
                if isinstance(summary_data, str):
                    try:
                        summary_data = json.loads(summary_data)
                    except json.JSONDecodeError:
                        # If it's not JSON, treat it as plain text
                        summary_data = {"headlines": [], "insights": summary_data}
                elif not isinstance(summary_data, dict):
                    summary_data = {"headlines": [], "insights": str(summary_data)}

                summaries.append({
                    "agent": row.agent,
                    "timestamp": row.timestamp,
                    "headlines": summary_data.get("headlines", []),
                    "insights": summary_data.get("insights", "")
                })
            except Exception as e:
                print(f"Failed to parse summary row {row.id}: {e}")
                print(f"Raw data: {row.data[:200]}...")
                continue

        return render_template("summaries.html", summaries=summaries)

@app.route("/api/configuration")
def api_configuration():
    """Get current system configuration"""
    try:
        current_config = {
            'gpt_model': get_gpt_model(),
            'prompt_config': get_prompt_version_config(),
            'trading_mode': get_trading_mode(),
            'config_hash': get_current_config_hash()
        }
        return jsonify(current_config)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route("/api/holdings")
def api_holdings():
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM holdings WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchall()
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/history")
def api_history():
    ticker = request.args.get("ticker")
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        if ticker:
            result = conn.execute(text("""
                SELECT current_price_timestamp, current_value FROM holdings
                WHERE ticker = :ticker AND config_hash = :config_hash 
                ORDER BY current_price_timestamp ASC
            """), {"ticker": ticker, "config_hash": config_hash}).fetchall()
        else:
            result = conn.execute(text("""
                SELECT current_timestamp, SUM(current_value) AS total_value
                FROM holdings
                WHERE config_hash = :config_hash
                GROUP BY current_timestamp ORDER BY current_timestamp ASC
            """), {"config_hash": config_hash}).fetchall()

        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/portfolio-history")
def api_portfolio_history():
    """Get portfolio performance over time"""
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, total_invested, 
                   total_profit_loss, percentage_gain, cash_balance
            FROM portfolio_history 
            WHERE config_hash = :config_hash
            ORDER BY timestamp ASC
        """), {"config_hash": config_hash}).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/portfolio-performance")
def api_portfolio_performance():
    """Get portfolio performance relative to initial $10,000 investment"""
    initial_investment = 10000.0
    config_hash = get_current_config_hash()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, cash_balance,
                   (total_portfolio_value - :initial_investment) as net_gain_loss,
                   ((total_portfolio_value - :initial_investment) / :initial_investment * 100) as net_percentage_gain
            FROM portfolio_history 
            WHERE config_hash = :config_hash
            ORDER BY timestamp ASC
        """), {"initial_investment": initial_investment, "config_hash": config_hash}).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/profit-loss")
def api_profit_loss():
    """Get current profit/loss breakdown by holding"""
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price,
                   total_value, current_value, gain_loss,
                   CASE 
                       WHEN total_value > 0 THEN (gain_loss / total_value * 100)
                       ELSE 0 
                   END as percentage_gain
            FROM holdings
            WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash
            ORDER BY gain_loss DESC
        """), {"config_hash": config_hash}).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route('/api/feedback')
def get_feedback_data():
    """Get feedback analysis data"""
    try:
        tracker = TradeOutcomeTracker()
        
        # Get recent feedback (gracefully handle missing AI key)
        try:
            latest_feedback = tracker.get_latest_feedback()
        except Exception:
            latest_feedback = None
        
        # Get trade outcomes for different periods
        periods = [7, 14, 30]
        period_data = {}
        
        for days in periods:
            # Compute metrics without AI call to avoid API failures impacting the dashboard
            metrics = tracker.compute_recent_outcomes_metrics(days_back=days)
            period_data[f'{days}d'] = {
                'total_trades': metrics['total_trades'],
                'success_rate': metrics['success_rate'],
                'avg_profit': metrics['avg_profit']
            }
        
        return jsonify({
            'latest_feedback': latest_feedback,
            'period_analysis': period_data,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'})

@app.route('/api/trade_outcomes')
def get_trade_outcomes():
    """Get recent trade outcomes"""
    try:
        config_hash = get_current_config_hash()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT ticker, sell_timestamp, purchase_price, sell_price, 
                       shares, gain_loss_amount, gain_loss_percentage, 
                       outcome_category, hold_duration_days
                FROM trade_outcomes 
                WHERE config_hash = :config_hash
                ORDER BY sell_timestamp DESC 
                LIMIT 50
            """), {"config_hash": config_hash}).fetchall()
            
            outcomes = []
            for row in result:
                outcomes.append({
                    'ticker': row.ticker,
                    'sell_date': row.sell_timestamp.isoformat() if row.sell_timestamp else None,
                    'purchase_price': float(row.purchase_price),
                    'sell_price': float(row.sell_price),
                    'shares': float(row.shares),
                    'net_gain_dollars': float(row.gain_loss_amount),
                    'gain_loss_pct': float(row.gain_loss_percentage),
                    'category': row.outcome_category,
                    'hold_days': row.hold_duration_days
                })
            
            return jsonify(outcomes)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/feedback_log')
def get_feedback_log():
    """Get feedback log with timestamps"""
    try:
        with engine.connect() as conn:
            # Get agent feedback entries
            config_hash = get_current_config_hash()
            feedback_result = conn.execute(text("""
                SELECT analysis_timestamp, lookback_period_days, total_trades_analyzed,
                       success_rate, avg_profit_percentage, summarizer_feedback, decider_feedback
                FROM agent_feedback 
                WHERE config_hash = :config_hash
                ORDER BY analysis_timestamp DESC 
                LIMIT 100
            """), {"config_hash": config_hash}).fetchall()
            
            # Get instruction updates
            instruction_result = conn.execute(text("""
                SELECT agent_type, update_timestamp, reason_for_update, performance_trigger
                FROM agent_instruction_updates 
                WHERE config_hash = :config_hash
                ORDER BY update_timestamp DESC 
                LIMIT 50
            """), {"config_hash": config_hash}).fetchall()
            
            feedback_log = []
            for row in feedback_result:
                feedback_log.append({
                    'type': 'feedback_analysis',
                    'timestamp': row.analysis_timestamp.isoformat() if row.analysis_timestamp else None,
                    'lookback_days': row.lookback_period_days,
                    'trades_analyzed': row.total_trades_analyzed,
                    'success_rate': float(row.success_rate) * 100,
                    'avg_profit': float(row.avg_profit_percentage) * 100,
                    'summarizer_feedback': row.summarizer_feedback,
                    'decider_feedback': row.decider_feedback
                })
            
            for row in instruction_result:
                feedback_log.append({
                    'type': 'instruction_update',
                    'timestamp': row.update_timestamp.isoformat() if row.update_timestamp else None,
                    'agent_type': row.agent_type,
                    'reason': row.reason_for_update,
                    'performance_trigger': row.performance_trigger
                })
            
            # Sort by timestamp descending
            feedback_log.sort(key=lambda x: x['timestamp'], reverse=True)
            
            return jsonify(feedback_log)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/generate_ai_feedback', methods=['POST'])
def generate_ai_feedback():
    """Generate AI feedback for a specific agent"""
    try:
        data = request.get_json()
        agent_type = data.get('agent_type')
        context_data = data.get('context_data')
        performance_metrics = data.get('performance_metrics')
        is_manual_request = data.get('is_manual_request', True)
        
        if not agent_type:
            return jsonify({'error': 'agent_type is required'}), 400
        
        # Initialize feedback tracker
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        # Generate AI feedback
        result = feedback_tracker.generate_ai_feedback_response(
            agent_type=agent_type,
            context_data=context_data,
            performance_metrics=performance_metrics,
            is_manual_request=is_manual_request
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai_feedback_responses')
def get_ai_feedback_responses():
    """Get recent AI feedback responses"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        limit = request.args.get('limit', 50, type=int)
        responses = feedback_tracker.get_recent_ai_feedback_responses(limit=limit)
        
        return jsonify(responses)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>')
def get_prompts(agent_type):
    """Get prompt history for an agent type"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        limit = request.args.get('limit', 10, type=int)
        prompts = feedback_tracker.get_prompt_history(agent_type, limit=limit)
        
        return jsonify(prompts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>/active')
def get_active_prompt(agent_type):
    """Get the currently active prompt for an agent type"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        prompt = feedback_tracker.get_active_prompt(agent_type)
        
        return jsonify(prompt if prompt else {'error': 'No active prompt found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>', methods=['POST'])
def save_prompt(agent_type):
    """Save a new prompt version for an agent type"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        data = request.get_json()
        user_prompt = data.get('user_prompt')
        system_prompt = data.get('system_prompt')
        description = data.get('description', '')
        created_by = data.get('created_by', 'system')
        
        if not user_prompt or not system_prompt:
            return jsonify({'error': 'user_prompt and system_prompt are required'}), 400
        
        version = feedback_tracker.save_prompt_version(
            agent_type=agent_type,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            description=description,
            created_by=created_by
        )
        
        return jsonify({
            'success': True,
            'version': version,
            'message': f'Prompt version {version} saved successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/feedback')
def feedback_dashboard():
    """Feedback analysis dashboard page"""
    return render_template('feedback_dashboard.html')

# Manual trigger endpoints for testing
@app.route('/api/trigger/summarizer', methods=['POST'])
def trigger_summarizer():
    """Manually trigger summarizer agents"""
    try:
        # Import the orchestrator to run summarizer
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run summarizer in a separate thread to avoid blocking
        def run_summarizer():
            try:
                orchestrator.run_summarizer_agents()
            except Exception as e:
                print(f"Error in manual summarizer run: {e}")
        
        thread = threading.Thread(target=run_summarizer, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Summarizer agents triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/decider', methods=['POST'])
def trigger_decider():
    """Manually trigger decider agent"""
    try:
        # Import the orchestrator to run decider
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run decider in a separate thread to avoid blocking
        def run_decider():
            try:
                orchestrator.run_decider_agent()
            except Exception as e:
                print(f"Error in manual decider run: {e}")
        
        thread = threading.Thread(target=run_decider, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Decider agent triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/feedback', methods=['POST'])
def trigger_feedback():
    """Manually trigger feedback agent"""
    try:
        # Import the orchestrator to run feedback
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run feedback in a separate thread to avoid blocking
        def run_feedback():
            try:
                orchestrator.run_feedback_agent()
            except Exception as e:
                print(f"Error in manual feedback run: {e}")
        
        thread = threading.Thread(target=run_feedback, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Feedback agent triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/price-update', methods=['POST'])
def trigger_price_update():
    """Manually trigger price updates for all holdings"""
    def run_price_update():
        try:
            print("=== Manual Price Update Triggered ===")
            config_hash = get_current_config_hash()
            with engine.begin() as conn:
                result = conn.execute(text("SELECT ticker FROM holdings WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash})
                tickers = [row.ticker for row in result]
                
                updated_count = 0
                for ticker in tickers:
                    try:
                        price = get_current_price_robust(ticker)
                        if price is None:
                            print(f"⚠️  Could not get price for {ticker}")
                            continue

                        now = datetime.utcnow()
                        conn.execute(text("""
                            UPDATE holdings
                            SET current_price = :price,
                                current_value = shares * :price,
                                gain_loss = (shares * :price) - total_value,
                                current_price_timestamp = :current_price_timestamp
                            WHERE ticker = :ticker AND config_hash = :config_hash"""), {
                                "price": price,
                                "current_price_timestamp": now,
                                "ticker": ticker,
                                "config_hash": config_hash
                            })
                        print(f"✅ Updated {ticker}: ${price:.2f}")
                        updated_count += 1
                    except Exception as e:
                        print(f"❌ Failed to update {ticker}: {e}")
                
                # Record portfolio snapshot after updates
                try:
                    record_portfolio_snapshot()
                    print("📊 Portfolio snapshot recorded")
                except Exception as e:
                    print(f"❌ Failed to record portfolio snapshot: {e}")
                
                print(f"🎯 Manual price update completed: {updated_count} holdings updated")
        except Exception as e:
            print(f"Error in manual price update: {e}")
    
    thread = threading.Thread(target=run_price_update, daemon=True)
    thread.start()
    return jsonify({
        'success': True,
        'message': 'Manual price update triggered successfully'
    })

@app.route('/api/trigger/all', methods=['POST'])
def trigger_all():
    """Manually trigger all agents in sequence"""
    try:
        # Import the orchestrator to run all agents
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run all agents in sequence in a separate thread
        def run_all():
            try:
                print("Starting manual run of all agents...")
                orchestrator.run_summarizer_agents()
                print("Summarizer completed, running decider...")
                orchestrator.run_decider_agent()
                print("Decider completed, running feedback...")
                orchestrator.run_feedback_agent()
                print("All agents completed successfully")
            except Exception as e:
                print(f"Error in manual all agents run: {e}")
        
        thread = threading.Thread(target=run_all, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'All agents triggered successfully (running in background)'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset-portfolio', methods=['POST'])
def reset_portfolio():
    """Reset portfolio to initial state with $10,000 cash"""
    try:
        config_hash = get_current_config_hash()
        with engine.begin() as conn:
            # Get current holdings to record them as sold for history (filter by config_hash)
            current_holdings = conn.execute(text("""
                SELECT ticker, shares, purchase_price, current_price, total_value, current_value, gain_loss
                FROM holdings
                WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash}).fetchall()
            
            # Record current holdings as sold for historical tracking
            for holding in current_holdings:
                if holding.shares > 0:
                    # Record as a sell transaction
                    conn.execute(text("""
                        INSERT INTO trade_outcomes (
                            ticker, sell_timestamp, purchase_price, sell_price, 
                            shares, gain_loss_amount, gain_loss_percentage, 
                            hold_duration_days, original_reason, sell_reason, outcome_category, config_hash
                        ) VALUES (
                            :ticker, CURRENT_TIMESTAMP, :purchase_price, :current_price,
                            :shares, :gain_loss, 
                            CASE WHEN :total_value > 0 THEN (:gain_loss / :total_value * 100) ELSE 0 END,
                            0, 'Portfolio reset', 'Portfolio reset', 'break_even', :config_hash
                        )
                    """), {
                        "ticker": holding.ticker,
                        "purchase_price": float(holding.purchase_price),
                        "current_price": float(holding.current_price),
                        "shares": float(holding.shares),
                        "gain_loss": float(holding.gain_loss),
                        "total_value": float(holding.total_value),
                        "config_hash": config_hash
                    })
            
            # Deactivate all current holdings
            conn.execute(text("""
                UPDATE holdings 
                SET is_active = FALSE, shares = 0, current_value = 0, gain_loss = 0
                WHERE ticker != 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash})
            
            # Reset cash to $10,000 (or create if not exists)
            cash_update_result = conn.execute(text("""
                UPDATE holdings 
                SET current_value = 10000, total_value = 10000, current_price = 10000
                WHERE ticker = 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash})
            
            # If no CASH holding exists, create it
            if cash_update_result.rowcount == 0:
                print(f"🚀 Creating initial CASH holding for config {config_hash}")
                conn.execute(text("""
                    INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price, purchase_timestamp, current_price_timestamp, total_value, current_value, gain_loss, reason, is_active)
                    VALUES (:config_hash, 'CASH', 1, 10000, 10000, now(), now(), 10000, 10000, 0, 'Reset to initial cash', TRUE)
                """), {"config_hash": config_hash})
            
            # Record portfolio snapshot after reset
            record_portfolio_snapshot()
            
            return jsonify({
                'success': True,
                'message': 'Portfolio reset successfully. Cash balance set to $10,000.'
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def clean_ticker_symbol(ticker):
    """Clean up ticker symbol to extract just the symbol"""
    if not ticker:
        return None
    
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
    
    return ticker

def get_current_price_robust(ticker):
    """Get current/last-close price with robust weekend/after-hours fallbacks"""
    # Clean the ticker symbol first
    clean_ticker = clean_ticker_symbol(ticker)
    if not clean_ticker:
        print(f"Invalid ticker symbol: {ticker}")
        return None

    try:
        stock = yf.Ticker(clean_ticker)

        # Fast info fields first
        try:
            fast_info = getattr(stock, 'fast_info', None)
            if fast_info:
                for key in (
                    'lastPrice',
                    'regularMarketPrice',
                    'regularMarketPreviousClose',
                ):
                    value = None
                    try:
                        value = fast_info.get(key) if hasattr(fast_info, 'get') else getattr(fast_info, key, None)
                    except Exception:
                        value = None
                    if value and float(value) > 0:
                        return float(value)
        except Exception:
            pass

        # Try info dict
        try:
            for key in ('currentPrice', 'regularMarketPrice', 'previousClose'):
                value = stock.info.get(key)
                if value and float(value) > 0:
                    return float(value)
        except Exception:
            pass

        # History with prepost, daily bars
        try:
            for period in ("1d", "5d"):
                hist = stock.history(period=period, interval="1d", prepost=True)
                if hist is not None and len(hist) > 0 and 'Close' in hist.columns:
                    close = hist['Close'].dropna()
                    if len(close) > 0:
                        return float(close.iloc[-1])
        except Exception:
            pass

        # Last 7 days range
        try:
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            hist = stock.history(start=start_date, end=end_date, interval="1d", prepost=True)
            if hist is not None and len(hist) > 0 and 'Close' in hist.columns:
                close = hist['Close'].dropna()
                if len(close) > 0:
                    return float(close.iloc[-1])
        except Exception:
            pass

        # yf.download over 1 month as a final fallback
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
                        return float(last_valid.iloc[-1])
        except Exception:
            pass

        # If all attempts fail, return None
        print(f"No price data available for {clean_ticker} (original: {ticker})")
        return None

    except Exception as e:
        print(f"Failed to fetch price for {clean_ticker} (original: {ticker}): {e}")
        return None

def update_prices():
    while True:
        time.sleep(REFRESH_INTERVAL_MINUTES * 60)
        config_hash = get_current_config_hash()
        with engine.begin() as conn:
            result = conn.execute(text("SELECT ticker FROM holdings WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash})
            tickers = [row.ticker for row in result]
            for ticker in tickers:
                try:
                    price = get_current_price_robust(ticker)
                    if price is None:
                        print(f"Skipping price update for {ticker} - no data available")
                        continue

                    now = datetime.utcnow()

                    conn.execute(text("""
                        UPDATE holdings
                        SET current_price = :price,
                            current_value = shares * :price,
                            gain_loss = (shares * :price) - total_value,
                            current_price_timestamp = :current_price_timestamp
                        WHERE ticker = :ticker AND config_hash = :config_hash"""), {
                            "price": price,
                            "current_price_timestamp": now,
                            "ticker": ticker,
                            "config_hash": config_hash
                        })
                    print(f"Updated price for {ticker}: ${price:.2f}")
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

@app.route('/api/schwab/holdings')
def get_schwab_holdings():
    """Get current Schwab holdings and portfolio data"""
    if not SCHWAB_ENABLED:
        return jsonify({
            'error': 'Schwab integration not available',
            'enabled': False
        })
    
    try:
        schwab_data = trading_interface.sync_schwab_positions()
        schwab_data['enabled'] = True
        return jsonify(schwab_data)
    except Exception as e:
        return jsonify({
            'error': str(e),
            'enabled': True,
            'status': 'error'
        })

@app.route('/api/schwab/account-info')
def get_schwab_account_info():
    """Get Schwab account information"""
    if not SCHWAB_ENABLED:
        return jsonify({
            'error': 'Schwab integration not available',
            'enabled': False
        })
    
    try:
        from schwab_client import schwab_client
        account_info = schwab_client.get_account_info()
        if account_info:
            return jsonify({
                'status': 'success',
                'account_info': account_info,
                'enabled': True
            })
        else:
            return jsonify({
                'error': 'Could not retrieve account information',
                'enabled': True,
                'status': 'error'
            })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'enabled': True,
            'status': 'error'
        })

@app.route('/schwab')
def schwab_dashboard():
    """Render the Schwab holdings dashboard"""
    return render_template('schwab_dashboard.html')

if __name__ == "__main__":
    start_price_updater()
    app.run(debug=True, port=8080)
