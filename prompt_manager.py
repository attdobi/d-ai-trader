"""
Prompt management utilities for using versioned prompts
"""
from sqlalchemy import text
from config import engine

def get_active_prompt(agent_type):
    """Get the currently active prompt for an agent type and config"""
    from config import get_current_config_hash
    config_hash = get_current_config_hash()
    
    with engine.connect() as conn:
        # First try to get config-specific prompt
        result = conn.execute(text("""
            SELECT system_prompt, user_prompt_template, version
            FROM prompt_versions
            WHERE agent_type = :agent_type AND is_active = TRUE AND config_hash = :config_hash
            ORDER BY version DESC
            LIMIT 1
        """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
        
        if result:
            return {
                "system_prompt": result.system_prompt,
                "user_prompt_template": result.user_prompt_template,
                "version": result.version
            }
        else:
            # Fallback to global v4 baseline
            result = conn.execute(text("""
                SELECT system_prompt, user_prompt_template, version
                FROM prompt_versions
                WHERE agent_type = :agent_type AND version = 4 AND (config_hash = 'global' OR config_hash IS NULL)
                LIMIT 1
            """), {"agent_type": agent_type}).fetchone()
            
            if result:
                print(f"⚠️  No config-specific prompt for {agent_type}, using global v4 baseline")
                return {
                    "system_prompt": result.system_prompt,
                    "user_prompt_template": result.user_prompt_template,
                    "version": result.version
                }
            else:
                raise ValueError(f"No prompts found for {agent_type}")

def create_new_prompt_version(agent_type, system_prompt, user_prompt_template, description, created_by="system"):
    """Create a new prompt version for the current config"""
    from config import get_current_config_hash
    config_hash = get_current_config_hash()
    
    with engine.begin() as conn:
        # Get the next version number for this config
        result = conn.execute(text("""
            SELECT COALESCE(MAX(version), 0) + 1 as next_version
            FROM prompt_versions
            WHERE agent_type = :agent_type AND config_hash = :config_hash
        """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
        
        next_version = result.next_version
        
        # Deactivate current prompts for this config
        conn.execute(text("""
            UPDATE prompt_versions
            SET is_active = FALSE
            WHERE agent_type = :agent_type AND config_hash = :config_hash
        """), {"agent_type": agent_type, "config_hash": config_hash})
        
        # Insert new version
        result = conn.execute(text("""
            INSERT INTO prompt_versions
            (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
            VALUES (:agent_type, :version, :system_prompt, :user_prompt_template, :description, :created_by, TRUE, :config_hash)
            RETURNING id, version
        """), {
            "agent_type": agent_type,
            "version": next_version,
            "system_prompt": system_prompt,
            "user_prompt_template": user_prompt_template,
            "description": description,
            "created_by": created_by,
            "config_hash": config_hash
        })
        
        new_prompt = result.fetchone()
        print(f"✅ Created {agent_type} v{new_prompt.version} for config {config_hash[:8]}")
        return new_prompt.id
