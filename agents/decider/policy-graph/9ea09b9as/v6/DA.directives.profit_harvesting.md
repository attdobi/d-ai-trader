---
id: DA.directives.profit_harvesting
version: DeciderAgent.9ea09b9as.v6
agent: DeciderAgent
title: "PROFIT HARVESTING"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#565
sep_before: ""
sep_after: "\n\n"
body_sha256: e7e0b19db659d682eef4b84764e27a9dfb7c546380dd1dfb246078670377c0dc
tags: []
tickers: []
---
PROFIT HARVESTING
- Any owned position ≥ +3% above cost is a default SELL full or majority unless a fresh ≤1 session catalyst is still price-confirmed.
- Profits are only real when realized; do not let +5% become flat because of narrative attachment.
- When media/crowd euphoria is obvious and the move is extended, fade by harvesting rather than chasing.
- If a winner is held instead of harvested, the reason must imply active catalyst freshness and current price confirmation.