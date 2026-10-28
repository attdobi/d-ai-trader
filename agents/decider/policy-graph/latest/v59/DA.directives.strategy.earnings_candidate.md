---
id: DA.directives.strategy.earnings_candidate
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: "EARNINGS CANDIDATE"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 12
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n"
body_sha256: 0bfffa6bc838cf85af1111b7971b9618271c50542b511d119755fe37ff138877
tags: []
tickers: []
---
10. EARNINGS CANDIDATE — IF a BUY candidate reports earnings within the next 5 sessions THEN reject it, writing earnings <date> inside hold window. Falsified if 20 such candidates average better than +1% over their next 5 sessions.