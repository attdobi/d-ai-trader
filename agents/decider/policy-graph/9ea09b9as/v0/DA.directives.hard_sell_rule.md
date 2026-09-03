---
id: DA.directives.hard_sell_rule
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "💰 HARD SELL RULE (NO CROWD-FADE OVERRIDES)"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 9
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#547
sep_before: ""
sep_after: "\n\n"
body_sha256: 3a108cd9d1304acac945914c6c82dea8bf0b9f353d77b21810df1b83ad1801d1
tags: []
tickers: []
---
💰 HARD SELL RULE (NO CROWD-FADE OVERRIDES)
- If gain ≥ +3% vs cost:
  • You MUST output `"action": "sell"` (full or majority). No HOLD is allowed.
  • Crowd-fade logic NEVER overrides this rule.
- Optional rare override:
  • You may HOLD a ≥ +3% winner only if there is a clearly stated, time-specific catalyst within ≤1 session (earnings tomorrow, court ruling today, etc.).
  • You must explicitly write: `HOLD despite +X% winner because <catalyst>; normally this is a SELL.` Use sparingly.
- When you SELL a winner, cite the approximate % gain (e.g., "+5.6%") and mention freeing settled/unsettled funds for the next trading day or rotation.