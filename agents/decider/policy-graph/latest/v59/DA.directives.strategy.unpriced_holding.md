---
id: DA.directives.strategy.unpriced_holding
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: "UNPRICED HOLDING"
node_type: rule
polarity: action
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 14
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n\n"
body_sha256: 2f3c0c110063503262b6700f2b28d6b0c199256152fb15a17fa94b57259073a5
tags: []
tickers: []
---
12. UNPRICED HOLDING — IF a confirmed Holding buy reason lacks numeric K:<price>;D:<%> THEN SELL in full, overriding any cost × 0.97 fallback. Otherwise next gate. Falsified if 20 such exits average above +1% over the next 3 sessions.