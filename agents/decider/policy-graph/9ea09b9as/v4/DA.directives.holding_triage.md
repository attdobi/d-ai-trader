---
id: DA.directives.holding_triage
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "HOLDING TRIAGE"
node_type: section
polarity: action
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 10
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#559
sep_before: ""
sep_after: "\n\n"
body_sha256: 2919d171c3d04da680a67fb2e07dab892caf3c483491d26668e13c95aeb7dcd7
tags: []
tickers: []
---
HOLDING TRIAGE
- A-quality hold: fresh ≤24–48h catalyst; above VWAP/opening range; strong 10m trend; relative strength vs SPY/sector; abnormal volume; near highs. HOLD or let breathe 1–3 days.
- B-quality monetize/trim: profitable but stale, extended, crowded, weakening, or lacking fresh catalyst. Prefer SELL full/majority, especially at +3% to +5%.
- C-quality exit: no fresh catalyst, failed catalyst, weak relative strength, below VWAP, weak 10m trend, near lows, or down >2% without confirmation. SELL full or at least majority.