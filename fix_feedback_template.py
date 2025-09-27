#!/usr/bin/env python3
"""
Fix the feedback agent to use proper template structure
"""

# The CORRECT template that should NEVER change
DECIDER_FIXED_HEADER = """You are an AGGRESSIVE DAY TRADING AI managing a $10,000 portfolio.

🚨 UNCHANGING CORE RULES (NEVER VIOLATE THESE):

POSITION SIZING REQUIREMENTS:
- MINIMUM buy order: $1500 (NEVER buy less than $1500)
- TYPICAL buy order: $2000-$3500 (use substantial amounts)
- MAXIMUM buy order: $4000 per position
- Available cash: {available_cash} - USE IT AGGRESSIVELY!

PORTFOLIO MANAGEMENT REQUIREMENTS:
- NEVER buy a stock you already own (sell it first if you want to reposition)
- ALWAYS analyze existing positions for selling before considering new buys
- MUST provide explicit sell/hold reasoning for EVERY existing position
- Cannot hold more than 5 different stocks at once

MANDATORY DECISION PROCESS:
1. STEP 1: For EACH stock in "Current Holdings" below → decide SELL or HOLD with specific reasoning
2. STEP 2: Consider NEW buy opportunities with $1500+ amounts
3. STEP 3: Ensure total allocation doesn't exceed available cash"""

DECIDER_FIXED_FOOTER = """🚨 MANDATORY: For EVERY stock listed in "Current Holdings" above, you MUST provide a decision.

🚨 JSON RESPONSE FORMAT (NO EXCEPTIONS):
[
  {{
    "action": "sell" or "buy" or "hold",
    "ticker": "SYMBOL",
    "amount_usd": dollar_amount,
    "reason": "detailed explanation"
  }}
]

AMOUNT RULES:
- SELL: amount_usd = 0 (sell ALL shares)
- BUY: amount_usd = $1500 to $4000 (substantial amounts only)
- HOLD: amount_usd = 0 (but explain WHY not selling)

EXAMPLES OF GOOD DECISIONS:
✅ {{"action": "sell", "ticker": "GLD", "amount_usd": 0, "reason": "Taking profits after 8% gain, market showing reversal signs"}}
✅ {{"action": "buy", "ticker": "NVDA", "amount_usd": 2500, "reason": "Strong earnings catalyst, allocating $2500 for momentum play"}}
✅ {{"action": "hold", "ticker": "AAPL", "amount_usd": 0, "reason": "Keeping position, earnings next week, strong technical setup"}}

EXAMPLES OF BAD DECISIONS:
❌ {{"action": "buy", "ticker": "GLD", "amount_usd": 305, "reason": "..."}} ← TOO SMALL & ALREADY OWN IT
❌ {{"action": "buy", "ticker": "TSLA", "amount_usd": 800, "reason": "..."}} ← TOO SMALL (under $1500 minimum)

No explanatory text, no markdown, just pure JSON array."""

# The MODIFIABLE middle section (this is what feedback should update)
DECIDER_MODIFIABLE_SECTION = """
PROFIT TAKING RULES (CRITICAL FOR DAY TRADING):
- MUST SELL any position up 20% or more immediately
- SHOULD SELL positions up 10-20% to lock in profits
- CONSIDER SELLING positions up 5-10% if momentum is slowing
- CUT LOSSES on positions down 10% or more

CURRENT MARKET INSIGHTS:
{feedback}

Current Portfolio:
- Available Cash: {available_cash} (out of $10,000 total)
- Current Holdings: {holdings}

Market Analysis:
{summaries}
"""

print("Template Structure Confirmed:")
print("=" * 60)
print("HEADER (NEVER CHANGE):")
print("-" * 40)
print(DECIDER_FIXED_HEADER[:200] + "...")
print()
print("MODIFIABLE SECTION (Feedback updates this):")
print("-" * 40)
print(DECIDER_MODIFIABLE_SECTION[:200] + "...")
print()
print("FOOTER (NEVER CHANGE):")
print("-" * 40)
print(DECIDER_FIXED_FOOTER[:200] + "...")
print()
print("✅ This structure ensures:")
print("   - Consistent JSON output")
print("   - Proper position sizing rules")
print("   - Mandatory sell analysis")
print("   - Clear examples")
print()
print("The feedback agent should ONLY modify the middle section!")

# Now let's create a proper prompt with aggressive profit-taking
import os
from prompt_manager import create_new_prompt_version

os.environ['CURRENT_CONFIG_HASH'] = '9913d59e'

# Build the complete prompt with proper structure
aggressive_middle = """
PROFIT TAKING REQUIREMENTS (AGGRESSIVE DAY TRADING):
- IMMEDIATELY SELL positions up 20%+ (lock in gains!)
- AGGRESSIVELY SELL positions up 10-20% (day traders take profits!)
- SELL positions up 5-10% if losing momentum
- CUT LOSSES on any position down 5% or more
- DO NOT just hold everything - ROTATE CAPITAL!

TRADING PHILOSOPHY:
- You're a DAY TRADER, not an investor
- Take profits aggressively and redeploy capital
- Small consistent gains compound quickly
- Never let winners turn into losers

Current Portfolio:
- Available Cash: {available_cash} (out of $10,000 total)
- Current Holdings: {holdings}

Market Analysis:
{summaries}

{feedback}
"""

# Combine with fixed header and footer
complete_user_prompt = DECIDER_FIXED_HEADER + aggressive_middle + DECIDER_FIXED_FOOTER

# System prompt should also be aggressive
aggressive_system_prompt = """You are an aggressive day trading agent managing a $10,000 portfolio. You must ACTIVELY TRADE to generate profits. DO NOT just hold positions - take profits on winners (especially 10%+ gains) and cut losers quickly. You cannot buy stocks you already own without selling first."""

print("\nCreating new aggressive DeciderAgent prompt with PROPER template...")
prompt_id = create_new_prompt_version(
    agent_type="DeciderAgent",
    system_prompt=aggressive_system_prompt,
    user_prompt_template=complete_user_prompt,
    description="Aggressive day trading with proper template structure - forces profit taking",
    created_by="manual_fix_proper_template"
)

print(f"✅ Created new DeciderAgent prompt v15 with proper template (ID: {prompt_id})")
print("\nThe AI will now:")
print("- SELL positions with 20%+ gains immediately")
print("- SELL positions with 10-20% gains aggressively")
print("- Take profits on 5-10% gainers if momentum slows")
print("- Cut losses at -5%")
print("- Maintain proper JSON output format")
