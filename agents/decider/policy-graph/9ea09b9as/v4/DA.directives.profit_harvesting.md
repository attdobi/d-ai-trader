---
id: DA.directives.profit_harvesting
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "PROFIT HARVESTING"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#559
sep_before: ""
sep_after: "\n\n"
body_sha256: b2ea17ccea11f4e9604dd2a9d75a68d787247e79e371f61c21d2a139262e6d40
tags: []
tickers: []
---
PROFIT HARVESTING
- Any owned position ≥ +3% above cost is a default SELL full or majority unless a fresh ≤1 session catalyst is still price-confirmed.
- Profits are only real when realized; do not let +5% become flat because of narrative attachment.
- When media/crowd euphoria is obvious and the move is extended, fade by harvesting rather than chasing.