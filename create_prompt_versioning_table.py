#!/usr/bin/env python3
"""
Create prompt versioning tables for tracking and managing prompts
"""
from sqlalchemy import text
from config import engine
from datetime import datetime

def create_prompt_versioning_tables():
    """Create tables for prompt version management"""
    with engine.begin() as conn:
        # Create prompt_versions table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id SERIAL PRIMARY KEY,
                agent_type VARCHAR(50) NOT NULL,
                version INTEGER NOT NULL,
                system_prompt TEXT,
                user_prompt_template TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(100) DEFAULT 'system',
                is_active BOOLEAN DEFAULT FALSE,
                performance_metrics JSONB,
                UNIQUE(agent_type, version)
            )
        """))
        
        # Create prompt_performance_history table to track how each version performs
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_performance_history (
                id SERIAL PRIMARY KEY,
                prompt_version_id INTEGER REFERENCES prompt_versions(id),
                config_hash VARCHAR(50),
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                total_trades INTEGER DEFAULT 0,
                successful_trades INTEGER DEFAULT 0,
                success_rate FLOAT,
                avg_profit_percentage FLOAT,
                total_profit_loss FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        print("✅ Created prompt versioning tables")
        
        # Insert baseline v4 prompts if they don't exist
        insert_baseline_prompts(conn)

def insert_baseline_prompts(conn):
    """Insert baseline v4 prompts for all agents"""
    
    # Check if v4 already exists
    existing = conn.execute(text("""
        SELECT COUNT(*) as count FROM prompt_versions WHERE version = 4
    """)).fetchone().count
    
    if existing > 0:
        print("ℹ️  v4 prompts already exist")
        return
    
    # Baseline prompts for v4
    baseline_prompts = [
        {
            "agent_type": "SummarizerAgent",
            "version": 4,
            "system_prompt": """You are a financial analysis assistant specialized in extracting actionable trading insights from news articles. Focus on concrete, time-sensitive information that could impact stock prices in the next 1-5 days.""",
            "user_prompt_template": """Analyze the following financial news and extract the most important actionable insights. Focus on:
1. Major market-moving events
2. Company-specific news that could impact stock prices
3. Sector trends and momentum shifts
4. Risk factors and warnings

Return a JSON object with:
- "headlines": A list of 3-5 most important headlines
- "insights": A paragraph summarizing key trading opportunities and risks

Content: {content}""",
            "description": "Baseline v4 prompt - balanced approach"
        },
        {
            "agent_type": "DeciderAgent",
            "version": 4,
            "system_prompt": """You are a day trading assistant making quick decisions based on current market news and momentum. Focus on stocks with clear catalysts and momentum. Be decisive but risk-aware.""",
            "user_prompt_template": """Based on the market analysis below, make specific trading decisions.

Current Portfolio:
- Available Cash: ${available_cash}
- Holdings: {holdings}

Market Analysis:
{summaries}

Recent Performance Feedback:
{feedback}

Make 1-3 specific trades. For each, return a JSON array with:
- "action": "buy" or "sell" or "hold"
- "ticker": Stock symbol
- "amount_usd": Dollar amount to trade
- "reason": Brief explanation

Focus on:
1. Strong momentum plays with clear catalysts
2. Quick profit taking (3-5% gains)
3. Cutting losses early (-5% stops)""",
            "description": "Baseline v4 prompt - momentum trading focus"
        }
    ]
    
    for prompt in baseline_prompts:
        conn.execute(text("""
            INSERT INTO prompt_versions 
            (agent_type, version, system_prompt, user_prompt_template, description, is_active)
            VALUES (:agent_type, :version, :system_prompt, :user_prompt_template, :description, TRUE)
        """), prompt)
    
    print("✅ Inserted baseline v4 prompts")

if __name__ == "__main__":
    create_prompt_versioning_tables()
    
    # Show current prompts
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT agent_type, version, description, is_active
            FROM prompt_versions
            ORDER BY agent_type, version
        """))
        
        print("\nCurrent prompt versions:")
        for row in result:
            status = "ACTIVE" if row.is_active else "inactive"
            print(f"  {row.agent_type} v{row.version}: {row.description} [{status}]")
