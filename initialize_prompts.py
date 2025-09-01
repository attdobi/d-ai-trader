#!/usr/bin/env python3
"""
Script to initialize default prompts in the database
"""

from feedback_agent import TradeOutcomeTracker

def initialize_default_prompts():
    """Initialize default prompts for all agent types"""
    tracker = TradeOutcomeTracker()
    
    # Default prompts for each agent type - ACTUAL TRADING PROMPTS (v0 baseline)
    default_prompts = {
        "SummarizerAgent": {
            "user_prompt_template": """Analyze the following financial news and extract the most important actionable insights.

{feedback_context}

Content: {content}

🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{{
    "headlines": ["headline 1", "headline 2", "headline 3"],
    "insights": "A comprehensive analysis paragraph focusing on actionable trading insights, market sentiment, and specific companies or sectors mentioned."
}}

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with {{ and ending with }}""",
            "system_prompt": """You are an intelligent financial analysis assistant specialized in extracting actionable trading insights from news articles. 

🚨 CRITICAL: You must ALWAYS respond with valid JSON format containing "headlines" array and "insights" string.

Focus on identifying trading opportunities, market sentiment shifts, and specific companies or sectors that could impact short-term trading decisions.""",
            "description": "v0 Baseline SummarizerAgent - extracts trading insights from financial news"
        },
        "DeciderAgent": {
            "user_prompt_template": """You are an AGGRESSIVE DAY TRADING AI. Make buy/sell recommendations for short-term trading based on the summaries and current portfolio.

Focus on INTRADAY to MAX 1-DAY holding periods for momentum and day trading. Target hourly opportunities, oversold bounces, and earnings-driven moves. Do not exceed 5 total trades, never allocate more than $9900 total.
Retain at least $100 in funds.

🚨 CRITICAL TRADING INSTRUCTIONS:
1. FIRST: Review each existing position and decide whether to SELL, providing explicit reasoning
2. SECOND: Consider new BUY opportunities based on news analysis  
3. Think in DOLLAR amounts, not share counts - the system will calculate shares

Current Portfolio:
- Available Cash: ${available_cash}
- Current Holdings: {holdings}

Market Analysis:
{summaries}

For each EXISTING holding above, you MUST provide a sell decision or explicit reasoning why you're keeping it.

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

No explanatory text, no markdown, just pure JSON array.""",
            "system_prompt": """You are an intelligent, machiavellian day trading agent tuned on extracting market insights and turning a profit. You are aggressive and focused on short-term gains and capital rotation. Learn from past performance feedback to improve decisions.""",
            "description": "v0 Baseline DeciderAgent - makes aggressive day trading decisions"
        },
        "feedback_analyzer": {
            "user_prompt": """You are a trading performance analyst. Review the current trading system performance and provide comprehensive feedback for system improvement.

Context Data: {context_data}
Performance Metrics: {performance_metrics}

Please provide:
1. Overall system performance analysis
2. Key strengths and weaknesses identified
3. Specific recommendations for both summarizer and decider agents
4. Market condition analysis and adaptation strategies
5. Long-term improvement suggestions

Focus on comprehensive insights that can guide the entire trading system's evolution.""",
            "system_prompt": """You are a senior trading system analyst providing comprehensive feedback for AI trading system improvement. 
Your analysis should be thorough, data-driven, and provide actionable insights for all system components.""",
            "description": "Default system analysis prompt - comprehensive system-wide feedback"
        }
    }
    
    # Save default prompts for each agent type
    for agent_type, prompt_data in default_prompts.items():
        try:
            # Use correct field names based on the prompt data structure
            user_prompt_field = "user_prompt_template" if "user_prompt_template" in prompt_data else "user_prompt"
            
            version = tracker.save_prompt_version(
                agent_type=agent_type,
                user_prompt=prompt_data[user_prompt_field],
                system_prompt=prompt_data["system_prompt"],
                description=prompt_data["description"],
                created_by="system"
            )
            print(f"✅ Initialized {agent_type} prompt (version {version})")
        except Exception as e:
            print(f"❌ Failed to initialize {agent_type} prompt: {e}")
    
    print("\n🎉 Default prompts initialized successfully!")
    print("You can now view and edit prompts through the dashboard.")

if __name__ == "__main__":
    initialize_default_prompts() 