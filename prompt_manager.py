"""
Prompt management utilities for using versioned prompts
"""
from sqlalchemy import text
from config import engine

PRIMARY_MISSION_BLOCK = """
PRIMARY MISSION (in priority order)
1) Harvest +3%–5%+ winners in current holdings so profits settle for the next session.
2) Rotate freed capital into 0–2 highest-conviction contrarian R1..Rk BUY setups if rails (min buy, caps, cash) permit.
3) Manage flat or losing positions only when the thesis breaks, risk limits trigger, or a superior setup requires the slot.
When priorities conflict, #1 outranks #2/#3 unless a fresh (≤1 session) catalyst makes holding a winner clearly superior.
"""

PROFIT_TAKING_DIRECTIVE = """
💰 PROFIT-TAKING DIRECTIVE (SELLS CAN OVERRIDE TICKET CAPS)
- On every cycle, scan each holding and tag it:
  • Winner (gain ≥ +3% vs cost) → default action = SELL (entire position, or ≥70% if fills require) to free settled cash for tomorrow.
  • Runner (+0% to +3%) → bias to HOLD unless the thesis or risk guardrail breaks.
- Ticket caps throttle new entries, not essential risk management. You may always execute SELLs required by this directive even if the daily ticket cap is technically reached.
- Keeping a Winner requires BOTH a documented new catalyst that emerged within the last session AND an explicit sentence explaining why holding beats banking the current gain.
- Every SELL reason for a Winner must cite the exact % gain and explicitly mention freeing settled funds (e.g., “SELL +5.6%, reload tomorrow”).
- If you keep a Winner, the HOLD reason must read “HOLD +4.2% because <fresh catalyst>; crowd is <behavior>, waiting for <specific trigger>.” Generic optimism is invalid.
- The average crowd clings to +3–5% pops hoping for moonshots; our edge is to sell into that euphoria and redeploy where fear or neglect misprices the next 1–5 day setup.
- If you ignore this directive, automation will forcibly convert your HOLD into a SELL — issue the SELL yourself so your reasoning matches the actual trade.
"""

USER_PLAN_BLOCK = """
PLAN (enforced sequence)
1) SELL or reduce every ≥+3% Winner unless a fresh ≤1-session catalyst makes holding mandatory (explain that catalyst explicitly).
2) With freed buying power, select up to 0–2 R1..Rk BUYs that fade obvious crowd behavior while respecting min/max sizing and daily caps.
3) For remaining positions (<+3% or no thesis break), HOLD unless the thesis or risk guardrail is broken.
Always ask: “Can I turn this gain into settled ammo for a higher-odds 1–5 day setup?”
"""

CASH_PROFIT_DISCLOSURE_BLOCK = """
CASH & PROFIT-TAKING DISCLOSURE
- If you output zero BUY actions while settled cash is available, add a "cash_reason" that:
  • States why no BUY (caps, cooldown, min-buy unmet, lack of edge, etc.), and
  • Confirms every ≥+3% Winner was harvested, or explicitly names any kept Winner with its % gain and fresh catalyst justification.
- Format the final object as {"decisions":[...], "cash_reason":"..."} only.
"""

def _apply_decider_overrides(agent_type, prompt_payload):
    if agent_type != "DeciderAgent" or not prompt_payload:
        return prompt_payload
    system_prompt = prompt_payload.get("system_prompt")
    if system_prompt:
        updated_system = system_prompt.rstrip()
        if "PRIMARY MISSION" not in updated_system:
            updated_system += "\n\n" + PRIMARY_MISSION_BLOCK.strip()
        if "💰 PROFIT-TAKING DIRECTIVE" not in updated_system:
            updated_system += "\n\n" + PROFIT_TAKING_DIRECTIVE.strip()
        prompt_payload["system_prompt"] = updated_system

    user_prompt = prompt_payload.get("user_prompt_template")
    if user_prompt:
        updated_user = user_prompt.rstrip()
        if "PLAN (enforced sequence)" not in updated_user:
            updated_user += "\n\n" + USER_PLAN_BLOCK.strip()
        if "CASH & PROFIT-TAKING DISCLOSURE" not in updated_user:
            updated_user += "\n\n" + CASH_PROFIT_DISCLOSURE_BLOCK.strip()
        prompt_payload["user_prompt_template"] = updated_user
    return prompt_payload

def _build_prompt_payload(agent_type, row):
    if not row:
        return None
    payload = {
        "system_prompt": row.system_prompt,
        "user_prompt_template": row.user_prompt_template,
        "version": row.version
    }
    return _apply_decider_overrides(agent_type, payload)

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
            payload = _build_prompt_payload(agent_type, result)
            if payload:
                return payload
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
                    payload = _build_prompt_payload(agent_type, result)
                    if payload:
                        return payload
            
            # Final fallback to global v0 baseline
            result = conn.execute(text("""
                SELECT system_prompt, user_prompt_template, version
                FROM prompt_versions
                WHERE agent_type = :agent_type AND version = 0 AND (config_hash = 'global' OR config_hash IS NULL)
                LIMIT 1
            """), {"agent_type": agent_type}).fetchone()
            
            if result:
                print(f"⚠️  Using global v0 baseline for {agent_type}")
                payload = _build_prompt_payload(agent_type, result)
                if payload:
                    return payload
            else:
                raise ValueError(f"No prompts found for {agent_type}")

def get_active_prompt_emergency_patch(agent_type):
    """Fetch active prompt with graceful baseline fallback for new configs."""
    from config import get_current_config_hash, engine
    from sqlalchemy import text

    config_hash = get_current_config_hash()

    def _fetch_prompt(conn):
        result = conn.execute(text("""
            SELECT system_prompt, user_prompt_template, version
            FROM prompt_versions
            WHERE agent_type = :agent_type AND is_active = TRUE AND config_hash = :config_hash
            ORDER BY version DESC LIMIT 1
        """), {"agent_type": agent_type, "config_hash": config_hash}).fetchone()
        if result:
            return {
                "system_prompt": result.system_prompt,
                "user_prompt_template": result.user_prompt_template,
                "version": result.version
            }
        return None

    try:
        with engine.connect() as conn:
            prompt = _fetch_prompt(conn)
            if prompt:
                return _apply_decider_overrides(agent_type, prompt)
    except Exception as e:
        print(f"⚠️ prompt_versions lookup error: {e}")

    try:
        if initialize_config_prompts(config_hash):
            with engine.connect() as conn:
                prompt = _fetch_prompt(conn)
                if prompt:
                    return _apply_decider_overrides(agent_type, prompt)
    except Exception as init_err:
        print(f"⚠️ Prompt initialization warning for {agent_type}: {init_err}")

    from initialize_prompts import DEFAULT_PROMPTS
    baselines = {
        agent: {
            "system_prompt": payload["system_prompt"],
            "user_prompt_template": payload["user_prompt_template"],
            "version": 0,
        }
        for agent, payload in DEFAULT_PROMPTS.items()
    }

    print(f"ℹ️ Using baseline prompt for {agent_type} (no active version found for config {config_hash})")
    prompt = baselines.get(agent_type, baselines["FeedbackAgent"])
    return _apply_decider_overrides(agent_type, prompt)

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
