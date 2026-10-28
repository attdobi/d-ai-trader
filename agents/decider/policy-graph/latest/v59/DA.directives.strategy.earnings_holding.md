---
id: DA.directives.strategy.earnings_holding
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: "EARNINGS HOLDING"
node_type: rule
polarity: action
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n"
body_sha256: e38edd9b3a9967d2852f58db942ea876a6c0a0dfac3479073cbf3afa35c940f2
tags: []
tickers: []
---
11. EARNINGS HOLDING — IF a holding reports earnings within 2 sessions THEN SELL before the print, or TRIM to half only when RISK-ON and up 3% or more. Falsified if 20 holdings kept through their print average better than +1%.