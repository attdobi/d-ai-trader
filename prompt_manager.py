"""
Prompt management utilities for using versioned prompts
"""
from sqlalchemy import text
from config import engine

def initialize_config_prompts(config_hash):
    """Initialize v0 baseline prompts for a new config"""
    print(f"🔧 Initializing v0 baseline prompts for config {config_hash[:8]}")
    
    with engine.connect() as conn:
        # Check if config already has prompts
        existing = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM prompt_versions
            WHERE config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchone()
        
        if existing.count > 0:
            print(f"  ⚠️  Config {config_hash[:8]} already has {existing.count} prompts")
            return False
        
        # Get global v0 baseline prompts
        baseline_result = conn.execute(text("""
            SELECT agent_type, system_prompt, user_prompt_template
            FROM prompt_versions
            WHERE version = 0 AND (config_hash = 'global' OR config_hash IS NULL)
            ORDER BY agent_type
        """))
        
        baseline_prompts = list(baseline_result)
        if not baseline_prompts:
            raise ValueError("No global v0 baseline prompts found!")
        
        # Create config-specific v0 prompts
        with engine.begin() as write_conn:
            for prompt in baseline_prompts:
                write_conn.execute(text("""
                    INSERT INTO prompt_versions
                    (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
                    VALUES (:agent_type, 0, :system_prompt, :user_prompt_template, :description, 'auto_init', TRUE, :config_hash)
                """), {
                    "agent_type": prompt.agent_type,
                    "system_prompt": prompt.system_prompt,
                    "user_prompt_template": prompt.user_prompt_template,
                    "description": f"v0 Baseline for config {config_hash[:8]} - auto-initialized",
                    "config_hash": config_hash
                })
                print(f"  ✅ Created {prompt.agent_type} v0")
        
        return True

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
            # Auto-initialize this config with v0 baseline if it doesn't exist
            print(f"🔧 Config {config_hash[:8]} has no prompts, auto-initializing...")
            initialized = initialize_config_prompts(config_hash)
            
            if initialized:
                # Try again to get the config-specific prompt
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
            
            # Final fallback to global v0 baseline
            result = conn.execute(text("""
                SELECT system_prompt, user_prompt_template, version
                FROM prompt_versions
                WHERE agent_type = :agent_type AND version = 0 AND (config_hash = 'global' OR config_hash IS NULL)
                LIMIT 1
            """), {"agent_type": agent_type}).fetchone()
            
            if result:
                print(f"⚠️  Using global v0 baseline for {agent_type}")
                return {
                    "system_prompt": result.system_prompt,
                    "user_prompt_template": result.user_prompt_template,
                    "version": result.version
                }
            else:
                raise ValueError(f"No prompts found for {agent_type}")

def create_new_prompt_version(agent_type, system_prompt, user_prompt_template, description, created_by="system"):
    """Create a new prompt version for the current config, reusing version numbers when possible"""
    from config import get_current_config_hash
    config_hash = get_current_config_hash()
    
    with engine.begin() as conn:
        # Check if we should reuse version numbers (when resetting from v0)
        current_active = conn.execute(text("""
            SELECT version
            FROM prompt_versions
            WHERE agent_type = :agent_type AND config_hash = :config_hash AND is_active = TRUE
        """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
        
        # If currently at v0, reuse v1 instead of creating v4, v5, etc.
        if current_active and current_active.version == 0:
            # We're evolving from v0, so use v1 (overwrite if it exists)
            target_version = 1
            print(f"🔄 Evolving from v0 → reusing v{target_version} for {agent_type}")
        else:
            # Get the next version number for this config
            result = conn.execute(text("""
                SELECT COALESCE(MAX(version), 0) + 1 as next_version
                FROM prompt_versions
                WHERE agent_type = :agent_type AND config_hash = :config_hash
            """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
            
            target_version = result.next_version
            print(f"📈 Creating new version v{target_version} for {agent_type}")
        
        # Deactivate current prompts for this config
        conn.execute(text("""
            UPDATE prompt_versions
            SET is_active = FALSE
            WHERE agent_type = :agent_type AND config_hash = :config_hash
        """), {"agent_type": agent_type, "config_hash": config_hash})
        
        # Check if target version already exists - if so, update it; if not, insert it
        existing_version = conn.execute(text("""
            SELECT id FROM prompt_versions
            WHERE agent_type = :agent_type AND config_hash = :config_hash AND version = :version
        """), {"agent_type": agent_type, "config_hash": config_hash, "version": target_version}).fetchone()
        
        if existing_version:
            # Update existing version
            conn.execute(text("""
                UPDATE prompt_versions
                SET system_prompt = :system_prompt,
                    user_prompt_template = :user_prompt_template,
                    description = :description,
                    created_by = :created_by,
                    is_active = TRUE,
                    created_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "system_prompt": system_prompt,
                "user_prompt_template": user_prompt_template,
                "description": description,
                "created_by": created_by,
                "id": existing_version.id
            })
            
            print(f"✅ Updated {agent_type} v{target_version} for config {config_hash[:8]} (overwritten)")
            return existing_version.id
        else:
            # Insert new version
            result = conn.execute(text("""
                INSERT INTO prompt_versions
                (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
                VALUES (:agent_type, :version, :system_prompt, :user_prompt_template, :description, :created_by, TRUE, :config_hash)
                RETURNING id, version
            """), {
                "agent_type": agent_type,
                "version": target_version,
                "system_prompt": system_prompt,
                "user_prompt_template": user_prompt_template,
                "description": description,
                "created_by": created_by,
                "config_hash": config_hash
            })
            
            new_prompt = result.fetchone()
            print(f"✅ Created {agent_type} v{new_prompt.version} for config {config_hash[:8]} (new)")
            return new_prompt.id
