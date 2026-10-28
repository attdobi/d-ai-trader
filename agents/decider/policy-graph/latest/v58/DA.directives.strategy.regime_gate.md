---
id: DA.directives.strategy.regime_gate
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "REGIME GATE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 3
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: 5ca4dd2bb6ec51e3da061640a0e98405777648ced19873e2a401b72bfbf80b0a
tags: []
tickers: []
---
1. REGIME GATE — IF INDEX REGIME is RISK-OFF THEN half size. Otherwise next gate. Falsified if 20 completed RISK-OFF half-size BUYs average below -0.75%.