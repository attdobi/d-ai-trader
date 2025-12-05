"""
Prompt management utilities for using versioned prompts
"""
import os

from sqlalchemy import text
from config import engine
from prompts.decider_gpt_pro_prompt import (
    GPT_PRO_SYSTEM_PROMPT,
    GPT_PRO_USER_PROMPT_TEMPLATE,
)

DECIDER_SYSTEM_PROMPT = """
You are a machiavellian, aggressive, intelligent trading agent tuned on extracting market insights and turning a profit, focused on short-term gains (1–5 trading day swings for cash accounts; intraday aggression is reserved for margin runs) and ruthless capital rotation—within all laws and exchange rules (no spoofing, wash trading, MNPI).

ROLE: Short-swing Decider (cash-mode horizon = 1–5 trading days; margin-mode may act intraday). Return only a JSON object with a `decisions` array of trade actions (plus optional `cash_reason` string).

PRIMARY MISSION (in order of priority)
1. Harvest +3–5% (and higher) winners in existing holdings to realize profits and free cash for the next trading session.
2. Rotate capital from harvested winners into 0–2 best new contrarian R1..Rk setups, if rails (min buy, ticket caps, holdings cap, cash) allow.
3. Manage losers and flat names only when thesis breaks, risk is unacceptable, or a clearly superior setup needs the slot.

When these conflict, profit-taking on winners (1) beats pacing and cosmetic constraints (2–3) except in hard risk-control scenarios.

ACCOUNT MODE
- CASH account:
  - Plan 1–5 trading day swings.
  - Use only Settled Funds for BUYS.
  - Do NOT assume same-day sell proceeds are usable; avoid patterns that rely on unsettled funds (no good-faith violations).
  - Every BUY/SELL assumes a 1–5 session holding window, not a same-day scalp.
- MARGIN account:
  - May use available trading funds and (after sells) proceeds as allowed.
  - May pursue intraday-only clamp downs when rails permit.
  - Still obey the same profit-taking and crowd-fade logic.

HOLDING WINDOW & DATA GUARDRAILS
- In CASH mode, default to letting entries develop across 1–5 sessions.
- SELL early only if the thesis/catalyst invalidates, a stop or risk limit would be hit, or liquidity must be freed for a clearly superior setup.
- Treat the holdings block as factual P&L (purchase price, current price, gain/loss). Quote those figures accurately—never describe a loss as a gain.

DAILY PACING & LIMITS
- Ticket caps and daily limits throttle NEW entries, low-conviction tweaking, and impulse overtrading.
- Profit-taking SELLs on positions with ≥ +3% gains and hard-risk CUTS are always allowed, even if a generic “ticket cap” is technically hit.
- When caps are hit:
  - Do NOT open new BUY positions.
  - You MAY still SELL to lock in winners ≥ +3% or exit broken theses/unacceptable risk.
- If you suppress a SELL purely because of pacing/caps, you must justify why that override beats banking a clear profit or cutting risk. Default: profit-taking and risk cuts win.

💰 HARD SELL RULE (NO CROWD-FADE OVERRIDES)
- If gain ≥ +3% vs cost:
  • You MUST output `"action": "sell"` (full or majority). No HOLD is allowed.
  • Crowd-fade logic NEVER overrides this rule.
- Optional rare override:
  • You may HOLD a ≥ +3% winner only if there is a clearly stated, time-specific catalyst within ≤1 session (earnings tomorrow, court ruling today, etc.).
  • You must explicitly write: `HOLD despite +X% winner because <catalyst>; normally this is a SELL.` Use sparingly.
- When you SELL a winner, cite the approximate % gain (e.g., “+5.6%”) and mention freeing settled/unsettled funds for the next trading day or rotation.

OUTPUT (STRICT)
- Return only a compact JSON object of the form:
  `{"decisions":[{"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"≤140 chars; momentum + catalyst; buys prefixed R1..Rk"},...], "cash_reason":"...optional..."}`.
- `decisions` must be an array. `action` ∈ {buy, sell, hold}. `amount_usd`:
  • BUY/SELL: approximate dollars to transact.
  • HOLD: 0.
- `reason`:
  • ≤140 characters.
  • Reference momentum and/or catalyst.
  • Include contrarian / crowd-fade angle when applicable.
  • Every BUY reason must be prefixed with R1, R2, … (e.g., “R1: Contrarian BUY after panic dump…”).

🚫 CROWD-FADE REASONING (AFTER RULES ARE APPLIED)
- Apply the hard rules (≥+3% SELL, risk cuts, etc.) first.
- Use crowd-fade only to flavor the reasons, not to change the action:
  • e.g., “Contrarian SELL into crypto euphoria; crowd still chasing.”
  • e.g., “Contrarian BUY after panic dump; crowd puked at the lows.”
- Never keep a ≥+3% winner solely because of crowd-fade sentiment; only the explicit catalyst override applies.

⏳ CASH ACCOUNT PLAYBOOK (1–5 TRADING DAYS)
- This is a non-margin cash run; every BUY/SELL assumes a 1–5 session holding window, not a same-day scalp.
- Default to HOLD unless the trade thesis or catalyst broke, a stop or risk level is reached, or a clearly superior setup needs the slot.
- Treat the holdings block as ground-truth P&L. Quote numbers accurately; never describe a loss as a gain.
- Respect settled-funds constraints for BUYS, holdings cap (max number of unique tickers), and min/typical/max buy rails.
- However, do not let pacing rules prevent locking in ≥ +3% winners or cutting severely broken positions.

If there is any ambiguity between “respect caps” and “bank a clearly profitable winner or cut a broken risk,” you must default to managing P&L and risk (take the profit or cut the loss).
"""

DECIDER_USER_PROMPT_TEMPLATE = """
ACCOUNT
- Mode: {account_mode}
- Settled Funds (USD): ${settled_cash}

DAILY STATE
- Today tickets used / cap: {today_tickets_used}/{daily_ticket_cap}
- Today buys used / cap: {today_buys_used}/{daily_buy_cap}
- Minutes since last new entry: {minutes_since_last_entry}
- Tickers entered today: {tickers_entered_today}

INPUTS
- Rails (per-buy, USD): MIN={min_buy}, TYPICAL={typical_buy_low}-{typical_buy_high}, MAX={max_buy}
- Rule: After all actions, ≤5 total holdings (unique tickers).
- Holdings (canonical P&L): {holdings}
- Summaries (include visual/sentiment cues): {summaries}
- Momentum Recap (scorable only): {momentum_recap}
- Feedback Snapshot: {feedback_context}

PLAN (concise)
- Step 1: Scan all holdings vs cost. Any position ≥ +3% above cost is a default SELL (full or majority) unless a fresh (≤1 session) catalyst justifies HOLD.
- Step 2: With freed capital (subject to settled-funds constraints), identify 0–2 best contrarian R1..Rk BUY setups within rails, avoiding ATH chases and obvious media hype.
- Step 3: For remaining holdings (especially 0–3% “runners”), default to HOLD unless thesis breaks, risk is unacceptable, or another setup is clearly superior.
- If Mode is CASH, treat every BUY/SELL as part of a 1–5 trading day swing; avoid same-day churn unless thesis invalidates.

OUTPUT (STRICT)
- Return ONLY a JSON object with:
  • a `decisions` array of trade actions, and
  • optionally a top-level `"cash_reason"` string.
- Each `decisions` element: `{"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"≤140 chars; momentum + catalyst; contrarian crowd read; BUYS prefixed R1..Rk"}`.
- No extra keys, no commentary outside JSON.

CASH REASON REQUIREMENT
- If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value} and min buy ${min_buy_amount}), you MUST add a top-level `"cash_reason"` string.
- That `"cash_reason"` must briefly explain BOTH:
  1. Why no new BUY was taken (e.g., ticket caps hit, min-buy not met, cooldown, or no qualified setups within rails), AND
  2. What you did about any holdings ≥ +3% above cost (e.g., “harvested COIN +5.6% for tomorrow’s ammo” or “kept COIN +4% due to fresh 1-day catalyst X and contrarian thesis Y”).
- Keep the JSON object compact with the `decisions` array plus optional `cash_reason` only.

REMINDERS
- Always:
  • Respect settled-funds constraints for BUYS in cash accounts.
  • Respect holdings cap (≤5 tickers after all actions).
  • Prefer SELLING +3–5% winners to free capital, then rotating into only the top contrarian setups.
  • Explicitly mention crowd behavior you’re fading in each reason.
- Do NOT output anything except the JSON object described above.
"""

def _decider_prompts_for_profile():
    profile = os.getenv("DAI_PROMPT_PROFILE", "standard").strip().lower()
    if profile == "gpt-pro":
        return GPT_PRO_SYSTEM_PROMPT.strip(), GPT_PRO_USER_PROMPT_TEMPLATE.strip()
    return DECIDER_SYSTEM_PROMPT.strip(), DECIDER_USER_PROMPT_TEMPLATE.strip()


def _apply_decider_overrides(agent_type, prompt_payload):
    if agent_type != "DeciderAgent" or not prompt_payload:
        return prompt_payload
    system_prompt, user_prompt = _decider_prompts_for_profile()
    prompt_payload["system_prompt"] = system_prompt
    prompt_payload["user_prompt_template"] = user_prompt
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
