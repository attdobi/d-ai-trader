#!/usr/bin/env python3
"""
Fix baseline prompts - create proper v0 trading prompts and make reset work correctly
"""

import os
import sys
from sqlalchemy import text
from config import engine, get_current_config_hash

def fix_baseline_prompts():
    """Fix the v0 baseline prompts to be actual trading prompts, not feedback prompts"""
    
    config_hash = get_current_config_hash()
    print(f"🔧 Fixing baseline prompts for config: {config_hash}")
    
    # Proper v0 baseline prompts for trading
    baseline_prompts = {
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
            "description": "v0 Baseline - extracts trading insights from financial news"
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
            "description": "v0 Baseline - makes aggressive day trading decisions"
        }
    }
    
    with engine.begin() as conn:
        for agent_type, prompt_data in baseline_prompts.items():
            # Check if v0 already exists for this config
            existing = conn.execute(text("""
                SELECT id FROM prompt_versions
                WHERE agent_type = :agent_type AND config_hash = :config_hash AND version = 0
            """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
            
            if existing:
                # Update existing v0
                conn.execute(text("""
                    UPDATE prompt_versions 
                    SET system_prompt = :system_prompt,
                        user_prompt_template = :user_prompt_template,
                        description = :description,
                        created_at = CURRENT_TIMESTAMP
                    WHERE agent_type = :agent_type AND config_hash = :config_hash AND version = 0
                """), {
                    "agent_type": agent_type,
                    "config_hash": config_hash,
                    "system_prompt": prompt_data["system_prompt"],
                    "user_prompt_template": prompt_data["user_prompt_template"],
                    "description": prompt_data["description"]
                })
                print(f"✅ Updated {agent_type} v0 baseline")
            else:
                # Create new v0
                conn.execute(text("""
                    INSERT INTO prompt_versions
                    (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
                    VALUES (:agent_type, 0, :system_prompt, :user_prompt_template, :description, 'fix_script', FALSE, :config_hash)
                """), {
                    "agent_type": agent_type,
                    "system_prompt": prompt_data["system_prompt"],
                    "user_prompt_template": prompt_data["user_prompt_template"],
                    "description": prompt_data["description"],
                    "config_hash": config_hash
                })
                print(f"✅ Created {agent_type} v0 baseline")
    
    print(f"\n🎯 Fixed baseline prompts for config {config_hash}")
    print("Now you can use the reset button to activate v0 baselines!")

def reset_to_baseline():
    """Reset current config to v0 baseline prompts"""
    config_hash = get_current_config_hash()
    print(f"🔄 Resetting to v0 baseline for config: {config_hash}")
    
    with engine.begin() as conn:
        # Deactivate all prompts for this config
        conn.execute(text("""
            UPDATE prompt_versions 
            SET is_active = FALSE
            WHERE config_hash = :config_hash
        """), {"config_hash": config_hash})
        
        # Activate v0 prompts
        result = conn.execute(text("""
            UPDATE prompt_versions 
            SET is_active = TRUE
            WHERE config_hash = :config_hash AND version = 0
        """), {"config_hash": config_hash})
        
        if result.rowcount > 0:
            print(f"✅ Reset to v0 baseline - {result.rowcount} prompts activated")
        else:
            print("❌ No v0 baseline prompts found - run fix_baseline_prompts() first")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_to_baseline()
    else:
        fix_baseline_prompts()
        if len(sys.argv) > 1 and sys.argv[1] == "--and-reset":
            reset_to_baseline()
