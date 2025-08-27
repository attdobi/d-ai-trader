import json
from datetime import datetime, timedelta
from sqlalchemy import text
from config import engine, PromptManager, session, openai, GPT_MODEL, get_model_token_params, get_model_temperature_params, get_current_config_hash
import yfinance as yf
import pandas as pd

# Performance thresholds
SIGNIFICANT_PROFIT_THRESHOLD = 0.05  # 5% gain considered significant
SIGNIFICANT_LOSS_THRESHOLD = -0.10   # 10% loss considered significant
FEEDBACK_LOOKBACK_DAYS = 30          # Days to look back for outcome analysis

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session)

class TradeOutcomeTracker:
    """Tracks outcomes of completed trades and provides feedback"""
    
    def __init__(self):
        self.ensure_outcome_tables_exist()
    
    def ensure_outcome_tables_exist(self):
        """Create tables for tracking trade outcomes and feedback"""
        with engine.begin() as conn:
            # Trade outcomes table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trade_outcomes (
                    id SERIAL PRIMARY KEY,
                    config_hash VARCHAR(50) NOT NULL,
                    ticker TEXT NOT NULL,
                    sell_timestamp TIMESTAMP NOT NULL,
                    purchase_price FLOAT NOT NULL,
                    sell_price FLOAT NOT NULL,
                    shares FLOAT NOT NULL,
                    gain_loss_amount FLOAT NOT NULL,
                    gain_loss_percentage FLOAT NOT NULL,
                    hold_duration_days INTEGER NOT NULL,
                    original_reason TEXT,
                    sell_reason TEXT,
                    outcome_category TEXT CHECK (outcome_category IN ('significant_profit', 'moderate_profit', 'break_even', 'moderate_loss', 'significant_loss')),
                    market_context JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Agent feedback table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id SERIAL PRIMARY KEY,
                    analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    config_hash VARCHAR(50),
                    lookback_period_days INTEGER NOT NULL,
                    total_trades_analyzed INTEGER NOT NULL,
                    success_rate FLOAT NOT NULL,
                    avg_profit_percentage FLOAT NOT NULL,
                    top_performing_patterns JSONB,
                    underperforming_patterns JSONB,
                    recommended_adjustments JSONB,
                    summarizer_feedback TEXT,
                    decider_feedback TEXT
                )
            """))
            
            # Add config_hash column to existing table if it doesn't exist
            try:
                conn.execute(text("""
                    ALTER TABLE agent_feedback 
                    ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)
                """))
            except Exception:
                pass  # Column might already exist
            
            # Agent instruction updates table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_instruction_updates (
                    id SERIAL PRIMARY KEY,
                    agent_type TEXT NOT NULL CHECK (agent_type IN ('summarizer', 'decider')),
                    update_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    original_instructions TEXT NOT NULL,
                    updated_instructions TEXT NOT NULL,
                    reason_for_update TEXT NOT NULL,
                    performance_trigger JSONB
                )
            """))
            
            # AI Agent Feedback Responses table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ai_agent_feedback_responses (
                    id SERIAL PRIMARY KEY,
                    agent_type TEXT NOT NULL CHECK (agent_type IN ('summarizer', 'decider', 'feedback_analyzer')),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_prompt TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    ai_response TEXT NOT NULL,
                    context_data JSONB,
                    performance_metrics JSONB,
                    feedback_category TEXT,
                    is_manual_request BOOLEAN DEFAULT FALSE
                )
            """))
            
            # AI Agent Prompts table for version control
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ai_agent_prompts (
                    id SERIAL PRIMARY KEY,
                    agent_type TEXT NOT NULL CHECK (agent_type IN ('summarizer', 'decider', 'feedback_analyzer')),
                    prompt_version INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_prompt TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    description TEXT,
                    is_active BOOLEAN DEFAULT FALSE,
                    created_by TEXT DEFAULT 'system',
                    triggered_by_feedback_id INTEGER REFERENCES ai_agent_feedback_responses(id)
                )
            """))
    
    def record_sell_outcome(self, ticker, sell_price, holding_data, sell_reason="Manual sell"):
        """Record the outcome of a sell transaction"""
        purchase_price = float(holding_data['purchase_price'])
        shares = float(holding_data['shares'])
        purchase_timestamp = holding_data.get('purchase_timestamp')
        
        gain_loss_amount = (sell_price - purchase_price) * shares
        gain_loss_percentage = (sell_price - purchase_price) / purchase_price
        
        # Calculate hold duration
        if purchase_timestamp:
            if isinstance(purchase_timestamp, str):
                purchase_date = datetime.fromisoformat(purchase_timestamp.replace('Z', '+00:00'))
            else:
                purchase_date = purchase_timestamp
            hold_duration = (datetime.utcnow() - purchase_date).days
        else:
            hold_duration = 0
        
        # Categorize outcome
        if gain_loss_percentage >= SIGNIFICANT_PROFIT_THRESHOLD:
            outcome_category = 'significant_profit'
        elif gain_loss_percentage > 0:
            outcome_category = 'moderate_profit'
        elif gain_loss_percentage >= -0.02:  # Within 2% is break even
            outcome_category = 'break_even'
        elif gain_loss_percentage >= SIGNIFICANT_LOSS_THRESHOLD:
            outcome_category = 'moderate_loss'
        else:
            outcome_category = 'significant_loss'
        
        # Get market context (simplified)
        market_context = self._get_market_context(ticker)
        
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO trade_outcomes 
                (config_hash, ticker, sell_timestamp, purchase_price, sell_price, shares, 
                 gain_loss_amount, gain_loss_percentage, hold_duration_days, 
                 original_reason, sell_reason, outcome_category, market_context)
                VALUES (:config_hash, :ticker, :sell_timestamp, :purchase_price, :sell_price, :shares,
                        :gain_loss_amount, :gain_loss_percentage, :hold_duration_days,
                        :original_reason, :sell_reason, :outcome_category, :market_context)
            """), {
                "config_hash": get_current_config_hash(),
                "ticker": ticker,
                "sell_timestamp": datetime.utcnow(),
                "purchase_price": purchase_price,
                "sell_price": sell_price,
                "shares": shares,
                "gain_loss_amount": gain_loss_amount,
                "gain_loss_percentage": gain_loss_percentage,
                "hold_duration_days": hold_duration,
                "original_reason": holding_data.get('reason', ''),
                "sell_reason": sell_reason,
                "outcome_category": outcome_category,
                "market_context": json.dumps(market_context)
            })
        
        print(f"Recorded {outcome_category} outcome for {ticker}: {gain_loss_percentage:.2%} gain/loss")
        return outcome_category
    
    def _get_market_context(self, ticker):
        """Get basic market context at time of sell"""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            if len(hist) > 1:
                recent_volatility = hist['Close'].pct_change().std()
                return {
                    "recent_volatility": float(recent_volatility) if not pd.isna(recent_volatility) else 0,
                    "volume_trend": "high" if hist['Volume'].iloc[-1] > hist['Volume'].mean() else "normal"
                }
        except:
            pass
        return {"recent_volatility": 0, "volume_trend": "unknown"}
    
    def analyze_recent_outcomes(self, days_back=FEEDBACK_LOOKBACK_DAYS):
        """Analyze recent trade outcomes and generate feedback"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        return self.analyze_recent_outcomes_for_config(config_hash, days_back)
    
    def analyze_recent_outcomes_for_config(self, config_hash, days_back=FEEDBACK_LOOKBACK_DAYS):
        """Analyze recent trade outcomes and generate feedback for a specific config"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        with engine.connect() as conn:
            # Get recent outcomes (exclude N/A actions from feedback analysis)
            result = conn.execute(text("""
                SELECT ticker, gain_loss_percentage, outcome_category, 
                       hold_duration_days, original_reason, sell_reason,
                       market_context
                FROM trade_outcomes 
                WHERE sell_timestamp >= :cutoff_date
                  AND config_hash = :config_hash
                  AND ticker != 'N/A'
                  AND original_reason NOT LIKE '%Market is closed%'
                ORDER BY sell_timestamp DESC
            """), {"cutoff_date": cutoff_date, "config_hash": config_hash})
            
            outcomes = [dict(row._mapping) for row in result]
        
        if not outcomes:
            print(f"No completed trades to analyze for config {config_hash} - analyzing decision patterns and generating feedback")
            # If no completed trades, analyze decision patterns and generate feedback anyway
            decision_analysis = self._analyze_decision_patterns_for_config(days_back, config_hash)
            
            # Generate feedback based on decision patterns even without trade outcomes
            if decision_analysis.get('total_decisions', 0) > 0:
                print(f"✅ Found {decision_analysis['total_decisions']} decisions to analyze for feedback")
                
                # Create synthetic feedback based on decision patterns
                synthetic_feedback = self._generate_decision_pattern_feedback_for_config(decision_analysis, config_hash)
                if synthetic_feedback:
                    print(f"🔄 Generated feedback from decision patterns for config {config_hash}")
                    
                    # Store feedback and auto-generate new prompts
                    feedback_id = self._store_feedback_for_config(
                        days_back, 
                        decision_analysis.get('total_attempts', decision_analysis.get('total_decisions', 0)), 
                        decision_analysis.get('parsing_success_rate', 1.0), 
                        0.0,  # No profit data 
                        decision_analysis, 
                        synthetic_feedback, 
                        config_hash
                    )
                    
                    # Auto-generate improved prompts from this feedback
                    if feedback_id:
                        print(f"🚀 Auto-generating improved prompts from decision pattern feedback...")
                        self._auto_generate_prompts_from_feedback_for_config(synthetic_feedback, feedback_id, config_hash)
                    
                    return {
                        'feedback_generated': True,
                        'feedback_source': 'decision_patterns',
                        'decisions_analyzed': decision_analysis['total_decisions'],
                        'feedback_content': synthetic_feedback,
                        'feedback_id': feedback_id
                    }
            
            return decision_analysis
        
        # Calculate metrics
        total_trades = len(outcomes)
        profitable_trades = len([o for o in outcomes if o['gain_loss_percentage'] > 0])
        success_rate = profitable_trades / total_trades if total_trades > 0 else 0
        avg_profit = sum(o['gain_loss_percentage'] for o in outcomes) / total_trades
        
        # Analyze patterns
        analysis = self._analyze_patterns(outcomes)
        
        # Generate AI feedback
        feedback = self._generate_ai_feedback_for_config(outcomes, success_rate, avg_profit, analysis, config_hash)
        
        # Store feedback
        feedback_id = self._store_feedback_for_config(days_back, total_trades, success_rate, 
                                                    avg_profit, analysis, feedback, config_hash)
        
        # Automatically create new prompts based on feedback for this config
        self._auto_generate_prompts_from_feedback_for_config(feedback, feedback_id, config_hash)
        
        return {
            "feedback_id": feedback_id,
            "success_rate": success_rate,
            "avg_profit": avg_profit,
            "total_trades": total_trades,
            "feedback": feedback
        }

    def _get_historical_feedback_summary(self, agent_type, max_feedbacks=10):
        """Get and summarize historical feedback for an agent type"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        return self._get_historical_feedback_summary_for_config(agent_type, config_hash, max_feedbacks)
    
    def _get_historical_feedback_summary_for_config(self, agent_type, config_hash, max_feedbacks=10):
        """Get and summarize historical feedback for an agent type and specific config"""
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT summarizer_feedback, decider_feedback, analysis_timestamp
                FROM agent_feedback 
                WHERE config_hash = :config_hash
                ORDER BY analysis_timestamp DESC 
                LIMIT :max_feedbacks
            """), {"max_feedbacks": max_feedbacks, "config_hash": config_hash}).fetchall()
            
            historical_insights = []
            for row in result:
                try:
                    if agent_type == 'summarizer':
                        fb_data = json.loads(row.summarizer_feedback)
                    else:
                        fb_data = json.loads(row.decider_feedback)
                    
                    if isinstance(fb_data, str):
                        historical_insights.append({
                            "date": row.analysis_timestamp.strftime("%Y-%m-%d"),
                            "feedback": fb_data[:200] + "..." if len(fb_data) > 200 else fb_data
                        })
                except (json.JSONDecodeError, AttributeError):
                    continue
            
            return historical_insights

    def _auto_generate_prompts_from_feedback(self, feedback, feedback_id):
        """Automatically generate new prompts based on feedback analysis with historical context"""
        try:
            # Get the config hash from environment (should be set by calling method)
            from config import get_current_config_hash
            config_hash = get_current_config_hash()
            
            summarizer_feedback = feedback.get('summarizer_feedback', '')
            decider_feedback = feedback.get('decider_feedback', '')
            
            if summarizer_feedback:
                # Get historical feedback for context - use the specific config hash
                historical_summarizer = self._get_historical_feedback_summary_for_config('summarizer', config_hash, max_feedbacks=5)
                
                # Create comprehensive summarizer prompt with historical context
                historical_context = ""
                if historical_summarizer:
                    historical_context = "\n\nHISTORICAL LESSONS LEARNED:\n"
                    for i, insight in enumerate(historical_summarizer[:3], 1):
                        historical_context += f"{i}. ({insight['date']}) {insight['feedback']}\n"
                
                # FIXED TEMPLATE COMPONENTS (never change)
                SUMMARIZER_BASE_INSTRUCTIONS = '''Analyze the following financial news and extract the most important actionable insights. Focus on:
1. Major market-moving events
2. Company-specific news that could impact stock prices
3. Sector trends and momentum shifts
4. Risk factors and warnings'''

                SUMMARIZER_JSON_FORMAT = '''{{feedback_context}}

Content: {{content}}

🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{{{{
    "headlines": ["headline 1", "headline 2", "headline 3"],
    "insights": "A comprehensive analysis paragraph focusing on actionable trading insights, market sentiment, and specific companies or sectors mentioned."
}}}}

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with {{{{ and ending with }}}}'''

                SUMMARIZER_SYSTEM_BASE = '''You are an intelligent, machiavellian day trading agent tuned on extracting market insights and turning a profit. You specialize in analyzing financial news articles and extracting actionable trading insights. Focus on concrete, time-sensitive information that could impact stock prices in the next 1-5 days.

🚨 CRITICAL: You must ALWAYS respond with valid JSON format containing "headlines" array and "insights" string as specified in the user prompt.'''

                # MODIFIABLE COMPONENTS (updated based on feedback)
                performance_guidance = f'''
LATEST PERFORMANCE FEEDBACK: {summarizer_feedback}{historical_context}

SPECIFIC INSIGHTS TO APPLY:
- Timing Patterns: {feedback.get('timing_patterns', 'Focus on market timing')}
- Risk Management: {feedback.get('risk_management', 'Maintain risk awareness')}
- Sector Analysis: {feedback.get('sector_insights', 'Monitor sector trends')}

Pay special attention to the images that portray positive or negative sentiment. Remember in some cases a new story and image could be shown for market manipulation. Though it is good to buy on optimism and sell on negative news it could also be a good time to sell and buy, respectively.

Learn from feedback to improve your analysis quality and focus on information that leads to profitable trades.'''

                # COMBINE: Fixed template + Modifiable feedback + Fixed format
                new_summarizer_user = f'''{SUMMARIZER_BASE_INSTRUCTIONS}

{performance_guidance}

{SUMMARIZER_JSON_FORMAT}'''

                new_summarizer_system = f'''{SUMMARIZER_SYSTEM_BASE}

INCORPORATE THE FOLLOWING PERFORMANCE INSIGHTS:
{summarizer_feedback}'''

                # Save the new summarizer prompt
                summarizer_version = self.save_prompt_version(
                    'summarizer', 
                    new_summarizer_user, 
                    new_summarizer_system,
                    f'Auto-generated from feedback analysis (ID: {feedback_id}) - performance-based improvements with fixed JSON format',
                    'feedback_automation'
                )
                print(f'✅ Auto-generated new summarizer prompt v{summarizer_version} from feedback (with fixed JSON format)')
            
            if decider_feedback:
                # Get historical feedback for context - use the specific config hash
                historical_decider = self._get_historical_feedback_summary_for_config('decider', config_hash, max_feedbacks=5)
                
                # Create comprehensive decider prompt with historical context
                historical_context = ""
                if historical_decider:
                    historical_context = "\n\nHISTORICAL LESSONS LEARNED:\n"
                    for i, insight in enumerate(historical_decider[:3], 1):
                        historical_context += f"{i}. ({insight['date']}) {insight['feedback']}\n"
                
                # FIXED TEMPLATE COMPONENTS (never change) - using hardcoded constants to avoid circular imports
                DECIDER_BASE_INSTRUCTIONS = '''You are an AGGRESSIVE DAY TRADING AI. Make buy/sell recommendations for short-term trading based on the summaries and current portfolio.

Focus on INTRADAY to MAX 1-DAY holding periods for momentum and day trading. Target hourly opportunities, oversold bounces, and earnings-driven moves. Do not exceed 5 total trades, never allocate more than $9900 total.
Retain at least $100 in funds.'''

                DECIDER_SYSTEM_BASE = '''You are an intelligent, machiavellian day trading agent tuned on extracting market insights and turning a profit. You are aggressive and focused on short-term gains and capital rotation. Learn from past performance feedback to improve decisions.'''

                # MODIFIABLE COMPONENTS (updated based on feedback)
                performance_guidance = f'''
LATEST PERFORMANCE FEEDBACK: {decider_feedback}{historical_context}

SPECIFIC INSIGHTS TO APPLY:
- Timing Patterns: {feedback.get('timing_patterns', 'Focus on optimal entry/exit timing')}
- Risk Management: {feedback.get('risk_management', 'Implement strict risk controls')}
- Sector Analysis: {feedback.get('sector_insights', 'Consider sector momentum')}'''

                # COMBINE: Fixed template + Modifiable feedback + JSON format requirement
                new_decider_user = f'''{DECIDER_BASE_INSTRUCTIONS}

{performance_guidance}

Current Portfolio: {{holdings}}
Available Cash: {{available_cash}}
News Summaries: {{summaries}}

🚨 CRITICAL: You must respond ONLY with valid JSON in this exact format:
[
  {{
    "action": "buy" or "sell" or "hold",
    "ticker": "SYMBOL",
    "amount_usd": dollar_amount_number,
    "reason": "brief explanation"
  }}
]
No explanatory text, no markdown, just pure JSON array.'''

                new_decider_system = f'''{DECIDER_SYSTEM_BASE}

INCORPORATE THE FOLLOWING PERFORMANCE INSIGHTS:
{decider_feedback}'''

                # Save the new decider prompt
                decider_version = self.save_prompt_version(
                    'decider',
                    new_decider_user, 
                    new_decider_system,
                    f'Auto-generated from feedback analysis (ID: {feedback_id}) - performance-based improvements with fixed format',
                    'feedback_automation'
                )
                print(f'✅ Auto-generated new decider prompt v{decider_version} from feedback (with fixed format)')
        
        except Exception as e:
            print(f"⚠️  Error auto-generating prompts from feedback: {e}")

    def compute_recent_outcomes_metrics(self, days_back=FEEDBACK_LOOKBACK_DAYS):
        """Compute recent outcome metrics only (no AI call)"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT gain_loss_percentage
                FROM trade_outcomes 
                WHERE sell_timestamp >= :cutoff_date AND config_hash = :config_hash
            """), {"cutoff_date": cutoff_date, "config_hash": config_hash})
            rows = [r.gain_loss_percentage for r in result]

        total_trades = len(rows)
        if total_trades == 0:
            return {"total_trades": 0, "success_rate": 0.0, "avg_profit": 0.0}

        profitable = sum(1 for v in rows if v > 0)
        success_rate = profitable / total_trades
        avg_profit = sum(rows) / total_trades

        return {
            "total_trades": total_trades,
            "success_rate": success_rate,
            "avg_profit": avg_profit,
        }
    
    def _analyze_patterns(self, outcomes):
        """Analyze patterns in trading outcomes"""
        # Group by outcome category
        by_category = {}
        for outcome in outcomes:
            category = outcome['outcome_category']
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(outcome)
        
        # Analyze reasons for good vs bad outcomes
        good_outcomes = [o for o in outcomes if o['gain_loss_percentage'] > SIGNIFICANT_PROFIT_THRESHOLD]
        bad_outcomes = [o for o in outcomes if o['gain_loss_percentage'] < SIGNIFICANT_LOSS_THRESHOLD]
        
        good_reasons = [o['original_reason'] for o in good_outcomes if o['original_reason']]
        bad_reasons = [o['original_reason'] for o in bad_outcomes if o['original_reason']]
        
        return {
            "outcome_distribution": {k: len(v) for k, v in by_category.items()},
            "successful_reasons": good_reasons,
            "unsuccessful_reasons": bad_reasons,
            "avg_hold_duration_profitable": sum(o['hold_duration_days'] for o in good_outcomes) / len(good_outcomes) if good_outcomes else 0,
            "avg_hold_duration_unprofitable": sum(o['hold_duration_days'] for o in bad_outcomes) / len(bad_outcomes) if bad_outcomes else 0
        }
    
    def _get_detailed_trade_analysis(self):
        """Get detailed individual trade data for pattern analysis"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT 
                    ticker,
                    purchase_price,
                    sell_price,
                    shares,
                    sell_timestamp,
                    gain_loss_percentage,
                    outcome_category,
                    original_reason,
                    sell_reason,
                    hold_duration_days,
                    market_context
                FROM trade_outcomes 
                WHERE sell_timestamp >= CURRENT_DATE - INTERVAL '30 days'
                  AND config_hash = :config_hash
                ORDER BY sell_timestamp DESC
                LIMIT 20
            """), {"config_hash": config_hash}).fetchall()
            
            trades = []
            for row in result:
                trades.append({
                    "symbol": row.ticker,
                    "buy_price": float(row.purchase_price),
                    "sell_price": float(row.sell_price),
                    "shares": row.shares,
                    "sell_date": row.sell_timestamp.strftime("%Y-%m-%d"),
                    "hold_days": row.hold_duration_days,
                    "gain_loss_pct": float(row.gain_loss_percentage),
                    "outcome": row.outcome_category,
                    "buy_reasoning": row.original_reason,
                    "sell_reasoning": row.sell_reason,
                    "market_context": row.market_context
                })
            
            return trades

    def _generate_ai_feedback_for_config(self, outcomes, success_rate, avg_profit, analysis, config_hash):
        """Generate AI feedback for a specific config without changing global state"""
        return self._generate_ai_feedback(outcomes, success_rate, avg_profit, analysis)
    
    def _store_feedback_for_config(self, lookback_days, total_trades, success_rate, avg_profit, analysis, feedback, config_hash):
        """Store feedback for a specific config"""
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_feedback 
                (config_hash, lookback_period_days, total_trades_analyzed, success_rate, avg_profit_percentage,
                 top_performing_patterns, underperforming_patterns, recommended_adjustments,
                 summarizer_feedback, decider_feedback)
                VALUES (:config_hash, :lookback_days, :total_trades, :success_rate, :avg_profit,
                        :top_patterns, :under_patterns, :adjustments, :summarizer_fb, :decider_fb)
                RETURNING id
            """), {
                "config_hash": config_hash,
                "lookback_days": lookback_days,
                "total_trades": total_trades,
                "success_rate": success_rate,
                "avg_profit": avg_profit,
                "top_patterns": json.dumps(analysis["successful_reasons"]),
                "under_patterns": json.dumps(analysis["unsuccessful_reasons"]),
                "adjustments": json.dumps(feedback),
                "summarizer_fb": json.dumps(feedback.get("summarizer_feedback", "")),
                "decider_fb": json.dumps(feedback.get("decider_feedback", ""))
            })
            return result.fetchone()[0]
    
    def _auto_generate_prompts_from_feedback_for_config(self, feedback, feedback_id, config_hash):
        """Generate prompts for a specific config without changing global state"""
        # Check if this config is in FIXED mode - if so, don't auto-update prompts
        try:
            with engine.connect() as conn:
                config_result = conn.execute(text("""
                    SELECT prompt_mode, forced_prompt_version
                    FROM run_configurations
                    WHERE config_hash = :config_hash
                """), {"config_hash": config_hash}).fetchone()
                
                if config_result and config_result.prompt_mode == 'fixed':
                    print(f"🔒 Config {config_hash} is in FIXED v{config_result.forced_prompt_version} mode - skipping auto-prompt updates")
                    return
        except Exception as e:
            print(f"❌ Error checking config mode for {config_hash}: {e}")
            return
        
        print(f"🔄 Config {config_hash} is in AUTO mode - generating simple prompt updates")
        
        # SIMPLIFIED: Generate basic prompt updates without complex historical context
        try:
            summarizer_feedback = feedback.get('summarizer_feedback', '')
            decider_feedback = feedback.get('decider_feedback', '')
            
            if summarizer_feedback:
                # Create simple updated summarizer prompt
                new_summarizer_system = f"""You are an intelligent, machiavellian day trading agent tuned on extracting market insights and turning a profit. You specialize in analyzing financial news articles and extracting actionable trading insights.

🚨 CRITICAL: You must ALWAYS respond with valid JSON format containing "headlines" array and "insights" string.

PERFORMANCE FEEDBACK: {summarizer_feedback}"""

                new_summarizer_user = """Analyze the following financial news and extract the most important actionable insights.

{feedback_context}

Content: {content}

🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{{
    "headlines": ["headline 1", "headline 2", "headline 3"],
    "insights": "A comprehensive analysis paragraph focusing on actionable trading insights, market sentiment, and specific companies or sectors mentioned."
}}

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with {{ and ending with }}"""

                # Save the updated prompt directly
                version = self._create_new_prompt_version_for_config(
                    'SummarizerAgent', 
                    new_summarizer_user, 
                    new_summarizer_system,
                    f'Auto-generated from feedback (ID: {feedback_id})',
                    config_hash
                )
                print(f"✅ Created summarizer prompt v{version} for config {config_hash}")
            
            if decider_feedback:
                # Create simple updated decider prompt
                new_decider_system = f"""You are an intelligent, machiavellian day trading agent tuned on extracting market insights and turning a profit. You are aggressive and focused on short-term gains and capital rotation.

PERFORMANCE FEEDBACK: {decider_feedback}"""

                new_decider_user = """You are an AGGRESSIVE DAY TRADING AI. Make buy/sell recommendations for short-term trading based on the summaries and current portfolio.

Focus on INTRADAY to MAX 1-DAY holding periods for momentum and day trading. Target hourly opportunities, oversold bounces, and earnings-driven moves. Do not exceed 5 total trades, never allocate more than $9900 total.
Retain at least $100 in funds.

LATEST PERFORMANCE FEEDBACK: {decider_feedback}

Current Portfolio: {holdings}
Available Cash: {available_cash}
News Summaries: {summaries}

🚨 CRITICAL: You must respond ONLY with valid JSON in this exact format:
[
  {{
    "action": "buy" or "sell" or "hold",
    "ticker": "SYMBOL",
    "amount_usd": dollar_amount_number,
    "reason": "brief explanation"
  }}
]
No explanatory text, no markdown, just pure JSON array."""

                # Save the updated prompt directly
                version = self._create_new_prompt_version_for_config(
                    'DeciderAgent', 
                    new_decider_user, 
                    new_decider_system,
                    f'Auto-generated from feedback (ID: {feedback_id})',
                    config_hash
                )
                print(f"✅ Created decider prompt v{version} for config {config_hash}")
                
        except Exception as e:
            print(f"❌ Error generating prompts for config {config_hash}: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_new_prompt_version_for_config(self, agent_type, user_prompt, system_prompt, description, config_hash):
        """Create a new prompt version for a specific config hash"""
        try:
            # Import here to avoid circular imports
            from prompt_manager import create_new_prompt_version
            
            # Temporarily set the config hash in environment
            import os
            original_hash = os.environ.get('CURRENT_CONFIG_HASH')
            os.environ['CURRENT_CONFIG_HASH'] = config_hash
            
            try:
                version = create_new_prompt_version(agent_type, user_prompt, system_prompt, description)
                return version
            finally:
                # Restore original hash
                if original_hash:
                    os.environ['CURRENT_CONFIG_HASH'] = original_hash
                elif 'CURRENT_CONFIG_HASH' in os.environ:
                    del os.environ['CURRENT_CONFIG_HASH']
                    
        except Exception as e:
            print(f"❌ Error creating prompt version for {agent_type} in config {config_hash}: {e}")
            return 0
    
    def _analyze_decision_patterns_for_config(self, days_back, config_hash):
        """Analyze decision patterns for a specific config"""
        return self._analyze_decision_patterns(days_back, config_hash)

    def _generate_ai_feedback(self, outcomes, success_rate, avg_profit, analysis):
        """Use AI to generate feedback for improving agent performance"""
        outcomes_summary = json.dumps({
            "total_trades": len(outcomes),
            "success_rate": success_rate,
            "avg_profit_percentage": avg_profit,
            "outcome_distribution": analysis["outcome_distribution"],
            "successful_patterns": analysis["successful_reasons"][:5],  # Top 5
            "unsuccessful_patterns": analysis["unsuccessful_reasons"][:5],
            "timing_insights": {
                "profitable_avg_hold_days": analysis["avg_hold_duration_profitable"],
                "unprofitable_avg_hold_days": analysis["avg_hold_duration_unprofitable"]
            }
        }, indent=2)
        
        # Get recent individual trades for detailed analysis
        recent_trades = self._get_detailed_trade_analysis()
        
        # FIXED TEMPLATE COMPONENTS (never change)
        FEEDBACK_BASE_INSTRUCTIONS = '''Analyze the following trading performance data and provide specific feedback to improve the performance of our AI trading agents.

Focus on:
1. Key insights about what's working well and what isn't  
2. Specific recommendations for the SUMMARIZER agents (how they should adjust their news analysis focus)
3. Specific recommendations for the DECIDER agent (how it should adjust its trading strategy)
4. Patterns in successful vs unsuccessful trades
5. Timing and market context insights - especially entry/exit timing
6. Specific trade examples of mistakes and successes'''

        # MODIFIABLE COMPONENTS (updated based on context data)
        performance_guidance = f'''
Performance Data:
{outcomes_summary}

Recent Trade Details (for pattern analysis):
{json.dumps(recent_trades, indent=2)}

ANALYSIS REQUIREMENTS:
- Focus on actionable improvements that can be incorporated into agent prompts and decision-making logic
- Pay special attention to entry and exit timing to maximize profits
- Create COMPREHENSIVE feedback that preserves important historical lessons
- Group insights by categories: timing, risk management, sector analysis, technical patterns
- Provide specific examples from the trade data
- Make feedback cumulative - build upon previous lessons rather than replacing them'''

        FEEDBACK_JSON_FORMAT = '''
🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{
    "summarizer_feedback": "Comprehensive recommendations for the summarizer agent including historical context",
    "decider_feedback": "Comprehensive recommendations for the decider agent including historical context", 
    "key_insights": ["insight 1", "insight 2", "insight 3", "insight 4", "insight 5"],
    "timing_patterns": "Specific patterns about entry/exit timing",
    "risk_management": "Risk management recommendations",
    "sector_insights": "Sector-specific trading insights"
}

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with { and ending with }'''

        # COMBINE: Fixed template + Modifiable performance data + Fixed JSON format
        prompt = f'''{FEEDBACK_BASE_INSTRUCTIONS}

{performance_guidance}

{FEEDBACK_JSON_FORMAT}'''

        FEEDBACK_SYSTEM_BASE = '''You are an intelligent, machiavellian day trading agent providing system-wide performance analysis. You are a trading performance analyst providing feedback to improve AI trading agents. Your analysis should be data-driven, specific, and actionable.'''

        system_prompt = f'''{FEEDBACK_SYSTEM_BASE}

CRITICAL INSTRUCTIONS:
1. Create COMPREHENSIVE feedback that preserves important historical lessons
2. Group insights by categories: timing, risk management, sector analysis, technical patterns  
3. Provide specific examples from the trade data
4. Include both tactical improvements (immediate actions) and strategic insights (long-term patterns)
5. Make feedback cumulative - build upon previous lessons rather than replacing them'''
        
        try:
            # Get the AI response using the same method as the new feedback system
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            # Get the correct parameters and use structured JSON schema

            token_params = get_model_token_params(GPT_MODEL, 2000)
            temperature_params = get_model_temperature_params(GPT_MODEL, 0.3)
            
            api_params = {
                "model": GPT_MODEL,
                "messages": messages,

                **token_params,  # Use max_tokens or max_completion_tokens based on model
                **temperature_params  # Use temperature or omit for GPT-5
            }
            
            print(f"🔧 Using simple JSON mode for FeedbackAgent")
            response = prompt_manager.client.chat.completions.create(**api_params)
            ai_response = response.choices[0].message.content.strip()
            
            # Parse the response to extract summarizer and decider feedback
            # The AI should provide structured feedback, but we'll handle it gracefully
            try:
                # Try to parse as JSON first
                feedback_data = json.loads(ai_response)
                return feedback_data
            except json.JSONDecodeError:
                # If not JSON, create a structured response from the text
                return {
                    "summarizer_feedback": ai_response,
                    "decider_feedback": ai_response,
                    "key_insights": [ai_response],
                    "timing_patterns": "Analysis provided in main feedback",
                    "risk_management": "Analysis provided in main feedback", 
                    "sector_insights": "Analysis provided in main feedback",
                    "raw_response": ai_response
                }
                
        except Exception as e:
            print(f"Failed to generate AI feedback: {e}")
            return {
                "summarizer_feedback": "Unable to generate AI feedback",
                "decider_feedback": "Unable to generate AI feedback",
                "key_insights": []
            }
    
    def _store_feedback(self, lookback_days, total_trades, success_rate, avg_profit, analysis, feedback):
        """Store the generated feedback in the database"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_feedback 
                (config_hash, lookback_period_days, total_trades_analyzed, success_rate, avg_profit_percentage,
                 top_performing_patterns, underperforming_patterns, recommended_adjustments,
                 summarizer_feedback, decider_feedback)
                VALUES (:config_hash, :lookback_days, :total_trades, :success_rate, :avg_profit,
                        :top_patterns, :under_patterns, :adjustments, :summarizer_fb, :decider_fb)
                RETURNING id
            """), {
                "config_hash": config_hash,
                "lookback_days": lookback_days,
                "total_trades": total_trades,
                "success_rate": success_rate,
                "avg_profit": avg_profit,
                "top_patterns": json.dumps(analysis["successful_reasons"]),
                "under_patterns": json.dumps(analysis["unsuccessful_reasons"]),
                "adjustments": json.dumps(feedback),
                "summarizer_fb": json.dumps(feedback.get("summarizer_feedback", "")),
                "decider_fb": json.dumps(feedback.get("decider_feedback", ""))
            })
            return result.fetchone()[0]
    
    def get_latest_feedback(self):
        """Get the most recent feedback for agent improvement"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT summarizer_feedback, decider_feedback, recommended_adjustments,
                       success_rate, avg_profit_percentage, total_trades_analyzed
                FROM agent_feedback 
                WHERE config_hash = :config_hash
                ORDER BY analysis_timestamp DESC 
                LIMIT 1
            """), {"config_hash": config_hash})
            row = result.fetchone()
            if row:
                return dict(row._mapping)
            return None
    
    def update_agent_instructions(self, agent_type, new_instructions, reason):
        """Record updates to agent instructions based on feedback"""
        # Get current instructions (this would need to be implemented based on how instructions are stored)
        current_instructions = self._get_current_instructions(agent_type)
        
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_instruction_updates 
                (agent_type, original_instructions, updated_instructions, reason_for_update)
                VALUES (:agent_type, :original, :updated, :reason)
            """), {
                "agent_type": agent_type,
                "original": current_instructions,
                "updated": new_instructions,
                "reason": reason
            })
        
        print(f"Updated {agent_type} instructions based on feedback")
    
    def _get_current_instructions(self, agent_type):
        """Get current instructions for an agent type"""
        # This would need to be implemented based on where instructions are stored
        # For now, return a placeholder
        return f"Current {agent_type} instructions"
    
    def generate_ai_feedback_response(self, agent_type, context_data=None, performance_metrics=None, is_manual_request=False):
        """Generate AI feedback response for a specific agent and store it"""
        
        # Try to get active prompt from database first
        active_prompt = self.get_active_prompt(agent_type)
        
        if active_prompt:
            # Use stored prompts
            user_prompt_template = active_prompt["user_prompt"]
            system_prompt = active_prompt["system_prompt"]
            
            # Format the user prompt with context data
            user_prompt = user_prompt_template.format(
                context_data=json.dumps(context_data, indent=2) if context_data else "No specific context provided",
                performance_metrics=json.dumps(performance_metrics, indent=2) if performance_metrics else "No performance data available"
            )
        else:
            # Fallback to hardcoded prompts (for backward compatibility)
            if agent_type == "summarizer":
                user_prompt_template = """
You are a financial summary agent helping a trading system. Analyze the current market conditions and provide feedback on how to improve news analysis and summarization.

Context Data: {context_data}
Performance Metrics: {performance_metrics}

Please provide:
1. Analysis of current summarization effectiveness
2. Specific recommendations for improving news analysis focus
3. Suggestions for better pattern recognition in financial news
4. Areas where the summarizer should pay more or less attention
5. Tips for identifying market manipulation vs genuine news

Focus on actionable improvements that can be incorporated into the summarizer's analysis approach.
"""
                system_prompt = """You are an expert financial analyst providing feedback to improve AI news summarization for trading decisions. 
Your analysis should be data-driven, specific, and actionable. Focus on patterns that can help the summarizer agent make better decisions."""
                
            elif agent_type == "decider":
                user_prompt_template = """
You are a trading decision-making AI. Analyze the current trading performance and provide feedback on how to improve trading strategy and decision-making.

Context Data: {context_data}
Performance Metrics: {performance_metrics}

Please provide:
1. Analysis of current trading strategy effectiveness
2. Specific recommendations for improving buy/sell decision timing
3. Suggestions for better risk management and position sizing
4. Areas where the decider should be more or less aggressive
5. Tips for identifying optimal entry and exit points

Focus on actionable improvements that can be incorporated into the decider's trading logic.
"""
                system_prompt = """You are an expert trading strategist providing feedback to improve AI trading decisions. 
Your analysis should be data-driven, specific, and actionable. Focus on patterns that can help the decider agent make better decisions."""
                
            elif agent_type == "feedback_analyzer":
                # FIXED TEMPLATE COMPONENTS (never change)
                FEEDBACK_BASE_INSTRUCTIONS = '''You are a trading performance analyst. Review the current trading system performance and provide comprehensive feedback for system improvement.

Focus on:
1. Overall system performance analysis
2. Key strengths and weaknesses identified  
3. Specific recommendations for both summarizer and decider agents
4. Market condition analysis and adaptation strategies
5. Long-term improvement suggestions'''

                FEEDBACK_JSON_FORMAT = '''
🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{{
    "summarizer_feedback": "Comprehensive recommendations for the summarizer agent",
    "decider_feedback": "Comprehensive recommendations for the decider agent", 
    "key_insights": ["insight 1", "insight 2", "insight 3", "insight 4", "insight 5"],
    "timing_patterns": "Specific patterns about entry/exit timing",
    "risk_management": "Risk management recommendations",
    "sector_insights": "Sector-specific trading insights"
}}

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with {{ and ending with }}'''

                FEEDBACK_SYSTEM_BASE = '''You are an intelligent, machiavellian day trading agent providing system-wide performance analysis. You are a senior trading system analyst providing comprehensive feedback for AI trading system improvement.'''

                # MODIFIABLE COMPONENTS (updated based on feedback - though feedback agent rarely gets feedback)
                performance_guidance = f'''
Context Data: {{context_data}}
Performance Metrics: {{performance_metrics}}

ANALYSIS FOCUS: Focus on comprehensive insights that can guide the entire trading system's evolution.'''

                # COMBINE: Fixed template + Modifiable feedback + Fixed JSON format
                user_prompt_template = f'''{FEEDBACK_BASE_INSTRUCTIONS}

{performance_guidance}

{FEEDBACK_JSON_FORMAT}'''

                system_prompt = f'''{FEEDBACK_SYSTEM_BASE}

Your analysis should be thorough, data-driven, and provide actionable insights for all system components.'''
            
            else:
                raise ValueError(f"Unknown agent type: {agent_type}")
            
            # Format the user prompt
            user_prompt = user_prompt_template.format(
                context_data=json.dumps(context_data, indent=2) if context_data else "No specific context provided",
                performance_metrics=json.dumps(performance_metrics, indent=2) if performance_metrics else "No performance data available"
            )
        
        try:
            # Get the AI response using the same method as summarizer/decider
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # Get the correct parameters and use structured JSON schema

            token_params = get_model_token_params(GPT_MODEL, 2000)
            temperature_params = get_model_temperature_params(GPT_MODEL, 0.3)
            
            api_params = {
                "model": GPT_MODEL,
                "messages": messages,

                **token_params,  # Use max_tokens or max_completion_tokens based on model
                **temperature_params  # Use temperature or omit for GPT-5
            }
            
            print(f"🔧 Using simple JSON mode for FeedbackAgent manual")
            response = prompt_manager.client.chat.completions.create(**api_params)
            ai_response = response.choices[0].message.content.strip()
            
            # Store the response in the database
            feedback_id = self._store_ai_feedback_response(
                agent_type=agent_type,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                ai_response=ai_response,
                context_data=context_data,
                performance_metrics=performance_metrics,
                is_manual_request=is_manual_request
            )
            
            return {
                "feedback_id": feedback_id,
                "response": ai_response,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"Failed to generate AI feedback for {agent_type}: {e}")
            return {
                "error": str(e),
                "response": f"Unable to generate AI feedback for {agent_type}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def _store_ai_feedback_response(self, agent_type, user_prompt, system_prompt, ai_response, context_data=None, performance_metrics=None, is_manual_request=False):
        """Store AI feedback response in the database"""
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO ai_agent_feedback_responses 
                (agent_type, user_prompt, system_prompt, ai_response, context_data, performance_metrics, is_manual_request)
                VALUES (:agent_type, :user_prompt, :system_prompt, :ai_response, :context_data, :performance_metrics, :is_manual_request)
                RETURNING id
            """), {
                "agent_type": agent_type,
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "ai_response": ai_response,
                "context_data": json.dumps(context_data) if context_data else None,
                "performance_metrics": json.dumps(performance_metrics) if performance_metrics else None,
                "is_manual_request": is_manual_request
            })
            return result.fetchone()[0]
    
    def get_recent_ai_feedback_responses(self, limit=50):
        """Get recent AI feedback responses"""
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, agent_type, timestamp, user_prompt, system_prompt, ai_response, 
                       context_data, performance_metrics, is_manual_request
                FROM ai_agent_feedback_responses 
                ORDER BY timestamp DESC 
                LIMIT :limit
            """), {"limit": limit})
            
            responses = []
            for row in result:
                # Handle context_data - it might be a dict or JSON string
                context_data = None
                if row.context_data:
                    if isinstance(row.context_data, dict):
                        context_data = row.context_data
                    else:
                        try:
                            context_data = json.loads(row.context_data)
                        except (json.JSONDecodeError, TypeError):
                            context_data = str(row.context_data)
                
                # Handle performance_metrics - it might be a dict or JSON string
                performance_metrics = None
                if row.performance_metrics:
                    if isinstance(row.performance_metrics, dict):
                        performance_metrics = row.performance_metrics
                    else:
                        try:
                            performance_metrics = json.loads(row.performance_metrics)
                        except (json.JSONDecodeError, TypeError):
                            performance_metrics = str(row.performance_metrics)
                
                responses.append({
                    "id": row.id,
                    "agent_type": row.agent_type,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "user_prompt": row.user_prompt,
                    "system_prompt": row.system_prompt,
                    "ai_response": row.ai_response,
                    "context_data": context_data,
                    "performance_metrics": performance_metrics,
                    "is_manual_request": row.is_manual_request
                })
            
            return responses
    
    def get_active_prompt(self, agent_type):
        """Get the currently active prompt for an agent type"""
        # Import here to avoid circular imports
        from config import should_use_specific_prompt_version, get_prompt_version_config
        
        with engine.connect() as conn:
            # Check if we should use a specific version instead of the latest
            if should_use_specific_prompt_version():
                config = get_prompt_version_config()
                forced_version = config["forced_version"]
                
                # Try to get the specific version first
                result = conn.execute(text("""
                    SELECT user_prompt_template as user_prompt, system_prompt, version as prompt_version, description
                    FROM prompt_versions
                    WHERE agent_type = :agent_type AND version = :version
                    LIMIT 1
                """), {"agent_type": agent_type, "version": forced_version})
                
                row = result.fetchone()
                if row:
                    print(f"🔒 Using FIXED prompt version {forced_version} for {agent_type}")
                    return {
                        "user_prompt": row.user_prompt,
                        "system_prompt": row.system_prompt,
                        "prompt_version": row.prompt_version,
                        "version": row.prompt_version,  # Add both for compatibility
                        "description": row.description
                    }
                else:
                    print(f"⚠️  Version {forced_version} not found for {agent_type}, falling back to latest")
            
            # Get the active prompt from the prompt_versions table for current config
            from config import get_current_config_hash
            config_hash = get_current_config_hash()
            
            result = conn.execute(text("""
                SELECT user_prompt_template as user_prompt, system_prompt, version as prompt_version, description
                FROM prompt_versions
                WHERE agent_type = :agent_type AND is_active = TRUE AND config_hash = :config_hash
                ORDER BY version DESC
                LIMIT 1
            """), {"agent_type": agent_type, "config_hash": config_hash})
            
            row = result.fetchone()
            if row:
                if not should_use_specific_prompt_version():
                    print(f"🔄 Using LATEST prompt version {row.prompt_version} for {agent_type}")
                return {
                    "user_prompt": row.user_prompt,
                    "system_prompt": row.system_prompt,
                    "prompt_version": row.prompt_version,
                    "version": row.prompt_version,  # Add both for compatibility
                    "description": row.description
                }
            return None
    
    def save_prompt_version(self, agent_type, user_prompt, system_prompt, description="", created_by="system", triggered_by_feedback_id=None):
        """Save a new version of prompts for an agent type"""
        from prompt_manager import create_new_prompt_version
        
        # Map old agent type names to new ones
        agent_type_mapping = {
            'summarizer': 'SummarizerAgent',
            'decider': 'DeciderAgent',
            'feedback_analyzer': 'FeedbackAgent'
        }
        
        mapped_agent_type = agent_type_mapping.get(agent_type, agent_type)
        
        # Use the new prompt versioning system
        prompt_id = create_new_prompt_version(
            agent_type=mapped_agent_type,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt,
            description=f"{description} (Auto-generated from feedback)",
            created_by=created_by
        )
        
        print(f"✅ Created new prompt version for {mapped_agent_type} (ID: {prompt_id})")
        
        # Get the version number that was created
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT version FROM prompt_versions WHERE id = :id
            """), {"id": prompt_id})
            
            version_row = result.fetchone()
            return version_row.version if version_row else None
    
    def get_prompt_history(self, agent_type, limit=10):
        """Get prompt history for an agent type and current config"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, version as prompt_version, created_at as timestamp, 
                       user_prompt_template as user_prompt, system_prompt, 
                       description, is_active, created_by, config_hash
                FROM prompt_versions
                WHERE agent_type = :agent_type AND config_hash = :config_hash
                ORDER BY version DESC 
                LIMIT :limit
            """), {"agent_type": agent_type, "config_hash": config_hash, "limit": limit})
            
            prompts = []
            for row in result:
                prompts.append({
                    "id": row.id,
                    "prompt_version": row.prompt_version,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "user_prompt": row.user_prompt,
                    "system_prompt": row.system_prompt,
                    "description": row.description,
                    "is_active": row.is_active,
                    "created_by": row.created_by,
                    "triggered_by_feedback_id": None,  # Not used in new system
                    "feedback_response": None  # Not used in new system
                })
            
            return prompts

    def _analyze_decision_patterns(self, days_back, config_hash):
        """Analyze recent trading decisions when no completed trades exist"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        with engine.connect() as conn:
            # Get ALL recent decisions to analyze parsing success rate
            all_decisions_result = conn.execute(text("""
                SELECT timestamp, data
                FROM trade_decisions 
                WHERE timestamp >= :cutoff_date
                  AND config_hash = :config_hash
                ORDER BY timestamp DESC
            """), {"cutoff_date": cutoff_date, "config_hash": config_hash})
            
            all_decisions = [dict(row._mapping) for row in all_decisions_result]
            
            # Get successful decisions (exclude pure N/A and parsing errors)
            successful_decisions_result = conn.execute(text("""
                SELECT timestamp, data
                FROM trade_decisions 
                WHERE timestamp >= :cutoff_date
                  AND config_hash = :config_hash
                  AND data::text NOT LIKE '%"action": "N/A"%'
                  AND data::text NOT LIKE '%Unable to parse%'
                  AND data::text NOT LIKE '%completely unparseable%'
                ORDER BY timestamp DESC
            """), {"cutoff_date": cutoff_date, "config_hash": config_hash})
            
            decisions = [dict(row._mapping) for row in successful_decisions_result]
            
            # Calculate parsing success rate
            total_attempts = len(all_decisions)
            successful_parses = len(decisions)
            parsing_success_rate = successful_parses / total_attempts if total_attempts > 0 else 0
        
        if not decisions:
            print("No recent decisions to analyze")
            return None
            
        # Parse and analyze decision patterns
        parsed_decisions = []
        for decision in decisions:
            try:
                decision_data = decision['data']
                if isinstance(decision_data, list) and len(decision_data) > 0:
                    decision_item = decision_data[0]  # Take first decision in list
                    parsed_decisions.append({
                        'timestamp': decision['timestamp'],
                        'action': decision_item.get('action', 'unknown'),
                        'ticker': decision_item.get('ticker', 'unknown'),
                        'amount_usd': decision_item.get('amount_usd', 0),
                        'reason': decision_item.get('reason', ''),
                        'execution_status': decision_item.get('execution_status', 'normal')
                    })
            except Exception as e:
                print(f"Error parsing decision: {e}")
                continue
        
        if not parsed_decisions:
            print("No parseable decisions to analyze")
            return None
        
        # Generate decision pattern feedback
        total_decisions = len(parsed_decisions)
        buy_decisions = len([d for d in parsed_decisions if d['action'] == 'buy'])
        deferred_decisions = len([d for d in parsed_decisions if d['execution_status'] == 'deferred'])
        
        # Analyze decision quality and patterns  
        action_distribution = {}
        for d in parsed_decisions:
            action = d['action']
            action_distribution[action] = action_distribution.get(action, 0) + 1
        
        decision_analysis = {
            "total_decisions": total_decisions,
            "total_attempts": total_attempts,
            "parsing_success_rate": parsing_success_rate,
            "action_distribution": action_distribution,
            "buy_decisions": buy_decisions,
            "deferred_decisions": deferred_decisions,
            "recent_tickers": list(set([d['ticker'] for d in parsed_decisions[:5]])),
            "decision_reasons": [d['reason'][:100] + "..." if len(d['reason']) > 100 else d['reason'] for d in parsed_decisions[:3]],
            # Add required fields for _store_feedback compatibility
            "outcome_distribution": {"decision_pattern_analysis": total_decisions},
            "successful_reasons": [d['reason'] for d in parsed_decisions if d['action'] == 'buy'][:5],
            "unsuccessful_reasons": [],  # No unsuccessful patterns for decisions
            "avg_hold_duration_profitable": 0,
            "avg_hold_duration_unprofitable": 0
        }
        
        # Generate AI feedback on decision patterns
        feedback = self._generate_decision_pattern_feedback(parsed_decisions, decision_analysis)
        
        # Store feedback
        feedback_id = self._store_feedback(days_back, total_decisions, 0, 0, decision_analysis, feedback)
        
        return {
            "feedback_id": feedback_id,
            "type": "decision_pattern_analysis",
            "total_decisions": total_decisions,
            "buy_decisions": buy_decisions,
            "deferred_decisions": deferred_decisions,
            "analysis": decision_analysis,
            "feedback": feedback
        }
        
    def _generate_decision_pattern_feedback_for_config(self, analysis, config_hash):
        """Generate AI feedback on decision-making patterns for a specific config"""
        try:
            # Focus on JSON parsing and response quality issues
            total_decisions = analysis.get('total_decisions', 0)
            parsing_success_rate = analysis.get('parsing_success_rate', 0)
            action_distribution = analysis.get('action_distribution', {})
            
            # Generate specific feedback for configs with parsing issues
            if parsing_success_rate < 0.8:  # Less than 80% parsing success
                feedback_text = f"""
Configuration {config_hash} is experiencing significant JSON parsing failures ({parsing_success_rate:.1%} success rate).

CRITICAL ISSUES IDENTIFIED:
1. AI responses are returning markdown/text instead of valid JSON
2. This causes "Unable to parse AI response" errors and defaults to hold
3. No actual buy/sell decisions are being executed
4. Prompt evolution is blocked due to lack of trade outcomes

IMMEDIATE FIXES NEEDED:
1. Enhance JSON formatting instructions in prompts
2. Add retry logic with simplified instructions for parsing failures  
3. Consider model-specific prompt templates (GPT-5 vs GPT-4)
4. Strengthen system prompt JSON requirements

DECISION PATTERN ANALYSIS:
- Total decisions attempted: {total_decisions}
- Parsing failures: {total_decisions * (1 - parsing_success_rate):.0f}
- Action distribution: {action_distribution}

RECOMMENDATIONS:
- Add explicit JSON schema examples to prompts
- Use clearer, simpler JSON format requirements
- Implement model-specific handling for GPT-5 series
- Test prompt modifications with sample data before deployment
"""
                return {
                    'summarizer_feedback': feedback_text,
                    'decider_feedback': feedback_text,
                    'key_insights': [
                        'JSON parsing failures preventing trade execution',
                        'Model-specific prompt formatting needed',
                        'Retry logic should include simplified instructions',
                        'Prompt evolution blocked without trade outcomes'
                    ]
                }
            
            return None
            
        except Exception as e:
            print(f"❌ Error generating decision pattern feedback: {e}")
            return None

    def _generate_decision_pattern_feedback(self, decisions, analysis):
        """Generate AI feedback on decision-making patterns"""
        try:
            # Use the global prompt_manager instance
            
            # Create analysis summary
            decision_summary = f"""
            Recent Decision Analysis:
            - Total decisions made: {analysis['total_decisions']}
            - Buy decisions: {analysis['buy_decisions']}
            - Deferred executions (market closed): {analysis['deferred_decisions']}
            - Recent tickers selected: {', '.join(analysis['recent_tickers'])}
            
            Sample decision reasons:
            {chr(10).join([f"- {reason}" for reason in analysis['decision_reasons']])}
            """
            
            user_prompt = f"""Analyze these recent trading decisions and provide feedback on decision-making quality, even though no trades have been executed yet.

{decision_summary}

Provide structured feedback focusing on:
1. Decision logic quality and consistency
2. Stock selection patterns and diversification
3. Risk management in decision sizing
4. Timing and market awareness
5. Recommendations for improvement

Return as JSON with keys: decision_quality, stock_selection, risk_management, timing_analysis, recommendations"""

            system_prompt = """You are an expert trading analyst providing feedback on AI trading decisions. Focus on the quality of the decision-making process, stock selection logic, and risk management practices. Be constructive and specific in your recommendations."""
            
            # Get AI model parameters
            token_params = get_model_token_params(GPT_MODEL, 1000)
            temperature_params = get_model_temperature_params(GPT_MODEL, 0.3)
            
            api_params = {
                "model": GPT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],

                **token_params,
                **temperature_params
            }
            
            response = prompt_manager.client.chat.completions.create(**api_params)
            ai_response = response.choices[0].message.content.strip()
            
            try:
                feedback_data = json.loads(ai_response)
                return feedback_data
            except json.JSONDecodeError:
                return {
                    "decision_quality": ai_response,
                    "stock_selection": "Analysis provided in main feedback",
                    "risk_management": "Analysis provided in main feedback",
                    "timing_analysis": "Analysis provided in main feedback",
                    "recommendations": "Analysis provided in main feedback",
                    "raw_response": ai_response
                }
                
        except Exception as e:
            print(f"Failed to generate decision pattern feedback: {e}")
            return {
                "decision_quality": "Unable to generate feedback",
                "error": str(e)
            }

def main():
    """Run feedback analysis on recent trades"""
    tracker = TradeOutcomeTracker()
    
    # Analyze recent outcomes
    feedback_result = tracker.analyze_recent_outcomes()
    
    if feedback_result:
        print(f"\n=== FEEDBACK ANALYSIS ===")
        print(f"Analyzed {feedback_result['total_trades']} recent trades")
        print(f"Success Rate: {feedback_result['success_rate']:.1%}")
        print(f"Average Profit: {feedback_result['avg_profit']:.2%}")
        print(f"\nFeedback stored with ID: {feedback_result['feedback_id']}")
        
        # Print key insights
        feedback = feedback_result['feedback']
        if isinstance(feedback, dict):
            if 'key_insights' in feedback:
                print(f"\nKey Insights: {feedback['key_insights']}")
            if 'summarizer_feedback' in feedback:
                print(f"\nSummarizer Feedback: {feedback['summarizer_feedback']}")
            if 'decider_feedback' in feedback:
                print(f"\nDecider Feedback: {feedback['decider_feedback']}")
    else:
        print("No recent trades found for analysis")

if __name__ == "__main__":
    main()