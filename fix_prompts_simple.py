#!/usr/bin/env python3
"""
Simple script to fix the prompt reset issue
"""

import os
import sys

# Set up environment
os.environ.setdefault('OPENAI_API_KEY', 'placeholder')
sys.path.append('.')

try:
    from config import engine, get_current_config_hash
    from sqlalchemy import text
    
    config_hash = get_current_config_hash()
    print(f"Current config: {config_hash}")
    
    # Check current active prompts
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT agent_type, version, is_active, description
            FROM prompt_versions 
            WHERE config_hash = :config_hash AND is_active = TRUE
            ORDER BY agent_type
        """), {"config_hash": config_hash}).fetchall()
        
        print("\n=== CURRENT ACTIVE PROMPTS ===")
        for row in result:
            print(f"{row.agent_type}: v{row.version} - {row.description}")
        
        # Check if v0 exists
        v0_result = conn.execute(text("""
            SELECT agent_type, version 
            FROM prompt_versions 
            WHERE config_hash = :config_hash AND version = 0
            ORDER BY agent_type
        """), {"config_hash": config_hash}).fetchall()
        
        print("\n=== v0 BASELINE PROMPTS ===")
        if v0_result:
            for row in v0_result:
                print(f"{row.agent_type}: v{row.version} exists")
        else:
            print("❌ NO v0 baseline prompts found - this is the problem!")
            print("The reset button can't reset to v0 because v0 doesn't exist.")
            
except Exception as e:
    print(f"Error: {e}")
