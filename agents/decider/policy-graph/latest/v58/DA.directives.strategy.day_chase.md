---
id: DA.directives.strategy.day_chase
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "DAY CHASE"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 9
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: 58247b4ffb5d62e7fc1ca13375d78a159e47424fe95f206a73624f6a1e14d835
tags: []
tickers: []
---
7. DAY CHASE — IF a name is up 8% or more on the day, or has gapped or gone parabolic, THEN reject it. Otherwise next gate. Falsified if 20 rejected names would have averaged better than +1.5% over the next 3 sessions.