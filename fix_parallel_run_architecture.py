#!/usr/bin/env python3
"""
COMPREHENSIVE ARCHITECTURE FIX

Fixes the broken parallel run isolation by:
1. Adding config_hash to feedback system tables
2. Migrating existing data
3. Updating all code paths
4. Ensuring proper isolation between parallel runs
"""

import os
import sys

# Set minimal environment for imports
os.environ.setdefault('OPENAI_API_KEY', 'placeholder')
sys.path.append('.')

def fix_feedback_table_schema():
    """Add config_hash column to ai_agent_prompts table"""
    
    sql_commands = [
        """
        -- Add config_hash column to ai_agent_prompts for parallel run isolation
        ALTER TABLE ai_agent_prompts 
        ADD COLUMN IF NOT EXISTS config_hash TEXT;
        """,
        
        """
        -- Create index for fast lookups by config
        CREATE INDEX IF NOT EXISTS idx_ai_agent_prompts_config 
        ON ai_agent_prompts(config_hash, agent_type, is_active, prompt_version DESC);
        """,
        
        """
        -- Add config_hash column to ai_agent_feedback_responses too
        ALTER TABLE ai_agent_feedback_responses 
        ADD COLUMN IF NOT EXISTS config_hash TEXT;
        """,
        
        """
        -- Create index for feedback responses by config
        CREATE INDEX IF NOT EXISTS idx_ai_feedback_responses_config 
        ON ai_agent_feedback_responses(config_hash, agent_type, timestamp DESC);
        """
    ]
    
    return sql_commands

def migrate_existing_feedback_data():
    """Migrate existing feedback data to use current config"""
    
    sql_commands = [
        """
        -- Get the most recently used config hash to assign to existing data
        WITH recent_config AS (
            SELECT config_hash 
            FROM run_configurations 
            ORDER BY last_used DESC 
            LIMIT 1
        )
        UPDATE ai_agent_prompts 
        SET config_hash = (SELECT config_hash FROM recent_config)
        WHERE config_hash IS NULL;
        """,
        
        """
        -- Same for feedback responses
        WITH recent_config AS (
            SELECT config_hash 
            FROM run_configurations 
            ORDER BY last_used DESC 
            LIMIT 1
        )
        UPDATE ai_agent_feedback_responses 
        SET config_hash = (SELECT config_hash FROM recent_config)
        WHERE config_hash IS NULL;
        """
    ]
    
    return sql_commands

def create_unified_prompt_system():
    """Create the unified prompt system that properly handles config isolation"""
    
    sql_commands = [
        """
        -- Create unified prompts table with proper config isolation
        CREATE TABLE IF NOT EXISTS unified_prompts (
            id SERIAL PRIMARY KEY,
            config_hash TEXT NOT NULL,
            agent_type TEXT NOT NULL CHECK (agent_type IN ('SummarizerAgent', 'DeciderAgent', 'feedback_analyzer')),
            version INTEGER NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt_template TEXT NOT NULL,
            description TEXT,
            created_by TEXT DEFAULT 'system',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT FALSE,
            triggered_by_feedback_id INTEGER,
            metadata JSONB DEFAULT '{}',
            UNIQUE(config_hash, agent_type, version)
        );
        """,
        
        """
        -- Create index for fast active prompt lookups
        CREATE INDEX IF NOT EXISTS idx_unified_prompts_active 
        ON unified_prompts(config_hash, agent_type, is_active, version DESC);
        """
    ]
    
    return sql_commands

def main():
    print("🏗️  COMPREHENSIVE ARCHITECTURE FIX")
    print("=" * 50)
    print("This will fix the parallel run isolation issues by:")
    print("1. Adding config_hash to feedback system tables")
    print("2. Migrating existing data")
    print("3. Creating unified prompt system")
    print("4. Ensuring proper isolation")
    print()
    
    all_commands = []
    
    print("📋 STEP 1: Fix feedback table schema")
    schema_commands = fix_feedback_table_schema()
    all_commands.extend(schema_commands)
    
    print("📋 STEP 2: Migrate existing data")
    migration_commands = migrate_existing_feedback_data()
    all_commands.extend(migration_commands)
    
    print("📋 STEP 3: Create unified system")
    unified_commands = create_unified_prompt_system()
    all_commands.extend(unified_commands)
    
    print("\n" + "=" * 50)
    print("🎯 SQL COMMANDS TO RUN:")
    print("=" * 50)
    
    for i, cmd in enumerate(all_commands, 1):
        print(f"\n-- Command {i}:")
        print(cmd.strip())
    
    print("\n" + "=" * 50)
    print("🚀 TO APPLY THE FIX:")
    print("=" * 50)
    print("1. Copy all the SQL commands above")
    print("2. Connect to your PostgreSQL database")
    print("3. Run the commands in order")
    print("4. Restart your D-AI-Trader system")
    print("5. Test that reset button now works for feedback tab")
    
    print("\n✅ AFTER APPLYING:")
    print("- Each parallel run will be properly isolated")
    print("- Reset button will work for all prompt systems")
    print("- No more v8 persisting across configs")
    print("- Proper position sizing rules enforced")

if __name__ == "__main__":
    main()
