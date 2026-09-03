---
id: DA.template.user
version: DeciderAgent.9ea09b9as.v2
agent: DeciderAgent
title: "User prompt template"
node_type: template
polarity: structure
polarity_source: override
parent: DA.root
field: user_prompt_template
order: 0
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#552
sep_before: ""
sep_after: ""
body_sha256: e94d0b02224def5b9432ba6a60c7c6af9d509a29f6a63b978ca56331679f3930
tags: []
tickers: []
---
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