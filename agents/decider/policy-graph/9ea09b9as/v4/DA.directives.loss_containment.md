---
id: DA.directives.loss_containment
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "LOSS CONTAINMENT"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 12
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#559
sep_before: ""
sep_after: "\n\n"
body_sha256: 98fce076983c827282230dce94b16028ad0c1386a1bbabb2c52254c598e921da
tags: []
tickers: []
---
LOSS CONTAINMENT
- Do not allow stale/no-catalyst losers to drift toward -6% to -8%.
- If an owned position is down >2% and lacks a fresh price-confirmed catalyst, SELL full or majority.
- If below VWAP plus weak 10m trend plus weak sector/index confirmation, treat as thesis failure unless an explicit fresh reversal catalyst exists.
- Never average down a failed catalyst in a cash account.