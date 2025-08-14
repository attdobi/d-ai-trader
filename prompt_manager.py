"""
Prompt management utilities for using versioned prompts
"""
from sqlalchemy import text
from config import engine

def get_active_prompt(agent_type):
    """Get the currently active prompt for an agent type"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT system_prompt, user_prompt_template, version
            FROM prompt_versions
            WHERE agent_type = :agent_type AND is_active = TRUE
            LIMIT 1
        """), {"agent_type": agent_type}).fetchone()
        
        if result:
            return {
                "system_prompt": result.system_prompt,
                "user_prompt_template": result.user_prompt_template,
                "version": result.version
            }
        else:
            # Fallback to v4 if no active prompt
            result = conn.execute(text("""
                SELECT system_prompt, user_prompt_template, version
                FROM prompt_versions
                WHERE agent_type = :agent_type AND version = 4
                LIMIT 1
            """), {"agent_type": agent_type}).fetchone()
            
            if result:
                return {
                    "system_prompt": result.system_prompt,
                    "user_prompt_template": result.user_prompt_template,
                    "version": result.version
                }
            else:
                raise ValueError(f"No prompts found for {agent_type}")

def create_new_prompt_version(agent_type, system_prompt, user_prompt_template, description, created_by="system"):
    """Create a new prompt version"""
    with engine.begin() as conn:
        # Get the next version number
        result = conn.execute(text("""
            SELECT COALESCE(MAX(version), 0) + 1 as next_version
            FROM prompt_versions
            WHERE agent_type = :agent_type
        """), {"agent_type": agent_type}).fetchone()
        
        next_version = result.next_version
        
        # Deactivate current prompts
        conn.execute(text("""
            UPDATE prompt_versions
            SET is_active = FALSE
            WHERE agent_type = :agent_type
        """), {"agent_type": agent_type})
        
        # Insert new version
        result = conn.execute(text("""
            INSERT INTO prompt_versions
            (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active)
            VALUES (:agent_type, :version, :system_prompt, :user_prompt_template, :description, :created_by, TRUE)
            RETURNING id, version
        """), {
            "agent_type": agent_type,
            "version": next_version,
            "system_prompt": system_prompt,
            "user_prompt_template": user_prompt_template,
            "description": description,
            "created_by": created_by
        })
        
        new_prompt = result.fetchone()
        print(f"✅ Created {agent_type} v{new_prompt.version}")
        return new_prompt.id
