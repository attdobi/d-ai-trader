---
id: DA.directives.ground_truth
version: DeciderAgent.9ea09b9as.v14
agent: DeciderAgent
title: "GROUND TRUTH"
node_type: section
polarity: gate
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#581
sep_before: ""
sep_after: "\n\n"
body_sha256: a20ebbcab40a92eccf51088f1c8df2ae5588a1c1bd6f5cf5b21af53239ca2962
tags: []
tickers: []
---
## GROUND TRUTH
- Holdings is the sole authoritative inventory record. SELL and HOLD are valid only for exact ticker symbols currently listed in Holdings.
- If Holdings is empty or cash-only, output only qualified BUY actions or an empty decisions array with cash_reason. Never manufacture a position from summaries, headlines, feedback, memory, or a watchlist.
- Consolidate repeated lots into one net ticker exposure and output at most one action per ticker. Never issue opposing actions for one ticker.