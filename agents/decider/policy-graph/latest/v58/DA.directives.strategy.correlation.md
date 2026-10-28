---
id: DA.directives.strategy.correlation
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: CORRELATION
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 7
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: 2d4551deb5228c1bd76d72ee3f7697386883fadecc84ed936e2bfaa2a5faf947
tags: []
tickers: []
---
5. CORRELATION — IF a BUY would make more than 2 semiconductor, AI-infrastructure, quantum or space names held at once THEN reject it. Otherwise next gate. Falsified if 10 rejected third names would have averaged better than +1.5% over the next 3 sessions.