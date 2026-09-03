---
id: DA.directives.strategy.priced_kill
version: DeciderAgent.9ea09b9as.v22
agent: DeciderAgent
title: "PRICED KILL"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 5
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#602
sep_before: ""
sep_after: "\n"
body_sha256: 752d0e46f8c74dc1f7f88e9ab1ab12aaaa57f5ca82a528f22e8ad6032f0408ca
tags: []
tickers: []
---
3. PRICED KILL — every BUY ends with K:<price>;D:<%>, K = the higher of (20d MA level or stated support, current price × 0.97). D ≤3% full size, ≤6% half size, >6% pass. K is binding on the first breach; a holding without a K price uses cost × 0.97. Falsified if the average loser under priced kills exceeds −3.5% over 20 losers.