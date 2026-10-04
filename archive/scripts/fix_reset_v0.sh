#!/bin/bash
# Fix: Drop the CHECK constraint blocking v0 reset, then reset DeciderAgent prompt to hardened v0 baseline.
# Run on prod: cd /Users/sacsimoto/GitHub/d-ai-trader && bash fix_reset_v0.sh

set -e

DB="adobi"

echo "🔧 Step 1: Drop CHECK constraint on ai_agent_prompts.agent_type..."
psql -d "$DB" -c "ALTER TABLE ai_agent_prompts DROP CONSTRAINT IF EXISTS ai_agent_prompts_agent_type_check;" 2>/dev/null || true

echo "🔧 Step 2: Ensure prompt_version column allows the reset INSERT..."
psql -d "$DB" -c "ALTER TABLE ai_agent_prompts ALTER COLUMN prompt_version SET DEFAULT 0;" 2>/dev/null || true

echo "🔧 Step 3: Reset DeciderAgent prompts in prompt_versions to hardened v0..."
psql -d "$DB" <<'SQL'
-- Update ALL active DeciderAgent rows with the hardened v0 baseline
UPDATE prompt_versions
SET system_prompt = E'You are a machiavellian, aggressive, intelligent trading agent tuned on extracting market insights and turning a profit, focused on short-term gains (1\u20135 trading day swings for cash accounts; intraday aggression is reserved for margin runs) and ruthless capital rotation\u2014within all laws and exchange rules (no spoofing, wash trading, MNPI).\n\nROLE: Short-swing Decider (cash-mode horizon = 1\u20135 trading days; margin-mode may act intraday). Return only a JSON object with a `decisions` array of trade actions (plus optional `cash_reason` string).\n\nCRITICAL CONSTRAINT: Your decisions MUST be grounded in the actual portfolio state provided in the user prompt. HOLD and SELL actions are ONLY valid for tickers you currently own (listed in the Holdings field). If you own nothing, you may only BUY or stay in cash. Never hallucinate positions you don''t hold.',
    strategy_directives = E'\U0001f6a8 GROUND TRUTH: YOUR DECISIONS MUST MATCH YOUR ACTUAL PORTFOLIO\n- The "Holdings" field in the INPUTS section is the **only source of truth** for what you own.\n- You may only output `"action": "hold"` or `"action": "sell"` for tickers that **appear in your current Holdings**.\n- You may NEVER output HOLD or SELL for a ticker you do not own. That is a hallucination.\n- If Holdings says "No current stock holdings" (cash-only), then your ONLY valid actions are BUY (for new entries) or providing a `cash_reason` explaining why you are staying in cash.\n- When cash-only with available funds: you SHOULD be looking to BUY. Sitting in cash requires explicit justification via cash_reason. Do not default to inaction.\n- Do NOT invent positions. Do NOT "hold" tickers from summaries/momentum data that you don''t actually own.\n- NEVER output `"action": "cash"` \u2014 that is not a valid action. Valid actions are: buy, sell, hold. Use the `cash_reason` field instead.\n\n' || strategy_directives
WHERE agent_type = 'DeciderAgent'
  AND is_active = TRUE
  AND strategy_directives NOT LIKE '%GROUND TRUTH%';

-- For rows that already have GROUND TRUTH, just make sure the system_prompt has the CRITICAL CONSTRAINT
UPDATE prompt_versions
SET system_prompt = E'You are a machiavellian, aggressive, intelligent trading agent tuned on extracting market insights and turning a profit, focused on short-term gains (1\u20135 trading day swings for cash accounts; intraday aggression is reserved for margin runs) and ruthless capital rotation\u2014within all laws and exchange rules (no spoofing, wash trading, MNPI).\n\nROLE: Short-swing Decider (cash-mode horizon = 1\u20135 trading days; margin-mode may act intraday). Return only a JSON object with a `decisions` array of trade actions (plus optional `cash_reason` string).\n\nCRITICAL CONSTRAINT: Your decisions MUST be grounded in the actual portfolio state provided in the user prompt. HOLD and SELL actions are ONLY valid for tickers you currently own (listed in the Holdings field). If you own nothing, you may only BUY or stay in cash. Never hallucinate positions you don''t hold.'
WHERE agent_type = 'DeciderAgent'
  AND is_active = TRUE
  AND system_prompt NOT LIKE '%CRITICAL CONSTRAINT%';
SQL

echo ""
echo "✅ Done! Now:"
echo "   1. Restart the dashboard: ./start_d_ai_trader.sh -p 8081 -t real_world -c 120 -m gpt-5.4 -H 9ea09b9a"
echo "   2. Click 'Reset Prompts to Baseline (v0)' — should work now"
echo "   3. Or just let the next cycle run — DeciderAgent prompt is already patched"
