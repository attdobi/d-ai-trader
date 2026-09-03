---
id: SA.directives.position_lot_accounting
version: SummarizerAgent.9ea09b9as.v14
agent: SummarizerAgent
title: "Position and lot accounting"
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#591
sep_before: ""
sep_after: "\n\n"
body_sha256: 0b6e69ba4e209896a991a1f91546368d62958576840aeb2a5b89e686921d449b
tags: []
tickers: []
---
## Position and lot accounting
- Treat repeated records for the same ticker with identical entry details as lot-level exits under one thesis, not independent trade ideas, unless the portfolio explicitly proves distinct entries or independent theses.
- Do not aggregate, net, or describe separate lots as a single position unless the synchronized portfolio explicitly provides the needed quantity and cost-basis information.
- For an inherited or synced holding, state only the ownership/inheritance fact actually shown. Do not infer entry date, prior rationale, risk level, or whether it is a fresh trade.