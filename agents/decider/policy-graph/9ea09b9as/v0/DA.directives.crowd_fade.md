---
id: DA.directives.crowd_fade
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "🚫 CROWD-FADE REASONING"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 10
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#547
sep_before: ""
sep_after: "\n\n"
body_sha256: 5482ff3867adb234ae7c3455972974fc95a0d7f4ed6f6f2d16a3b3a9ae885778
tags: []
tickers: []
---
🚫 CROWD-FADE REASONING
- Apply the hard rules first (≥+3% SELL, risk cuts, etc.).
- Use crowd-fade only to flavor the reasons, not to change the action:
  • e.g., "Contrarian SELL into crypto euphoria; crowd still chasing."
  • e.g., "Contrarian BUY after panic dump; crowd puked at the lows."
- Never keep a ≥+3% winner solely because of crowd-fade sentiment; only the explicit catalyst override applies.