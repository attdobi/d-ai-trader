#!/usr/bin/env python3
"""
Test what config hash the dashboard is using
"""
import os

# Test 1: What's in the environment?
print("Environment Check:")
print(f"CURRENT_CONFIG_HASH from env: {os.environ.get('CURRENT_CONFIG_HASH', 'NOT SET')}")

# Test 2: What does get_current_config_hash return?
from config import get_current_config_hash, get_current_configuration
print(f"\nget_current_config_hash(): {get_current_config_hash()}")

# Test 3: What configuration would generate that hash?
config = get_current_configuration()
print(f"\nCurrent Configuration:")
print(f"  Config Hash: {config['config_hash']}")
print(f"  Model: {config['gpt_model']}")
print(f"  Prompt Mode: {config['prompt_mode']}")
print(f"  Description: {config['description']}")

# Test 4: Check what prompts exist for the dashboard's config
from sqlalchemy import text
from config import engine

print(f"\n9913d59e Configuration (from dashboard):")
with engine.connect() as conn:
    # Check what this config is
    result = conn.execute(text("""
        SELECT gpt_model, prompt_mode, forced_prompt_version, trading_mode
        FROM run_configurations
        WHERE config_hash = '9913d59e'
    """)).fetchone()
    
    if result:
        print(f"  Model: {result.gpt_model}")
        print(f"  Mode: {result.prompt_mode}")
        print(f"  Forced Version: {result.forced_prompt_version}")
        
    # Check active prompts
    result = conn.execute(text("""
        SELECT agent_type, version
        FROM prompt_versions
        WHERE config_hash = '9913d59e' AND is_active = true
    """))
    
    print(f"\nActive Prompts for 9913d59e:")
    for row in result:
        print(f"  {row.agent_type}: v{row.version}")

# Test 5: Check if there are v0 prompts
print(f"\nChecking for v0 prompts:")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT config_hash, agent_type, version, is_active
        FROM prompt_versions
        WHERE version = 0 AND is_active = true
        ORDER BY config_hash, agent_type
    """))
    
    for row in result:
        print(f"  Config {row.config_hash}: {row.agent_type} v{row.version} (active={row.is_active})")
