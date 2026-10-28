---
id: DA.directives.strategy.harvest
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: HARVEST
node_type: rule
polarity: action
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n"
body_sha256: 0295d3e4cabd5ac37b70ed887309fa617c340b3cee9c1c4cbafa967d377478d7
tags: []
tickers: []
---
6. HARVEST — IF a holding is up 3% or more, or 2% in RISK-OFF, THEN SELL it in full unless a catalyst no older than 1 session is still price-confirmed and the regime is RISK-ON. Falsified if 20 harvested winners would have gained 2% more over the next 3 sessions.