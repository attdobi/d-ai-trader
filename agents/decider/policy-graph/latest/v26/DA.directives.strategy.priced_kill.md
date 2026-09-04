---
id: DA.directives.strategy.priced_kill
version: DeciderAgent.9ea09b9as.v26
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
provenance: prompt_versions#612
sep_before: ""
sep_after: "\n"
body_sha256: 1d120cd8d4b2648e47204bb540575669850562cacaf5c8dfbc7637bbdf483d5b
tags: []
tickers: []
---
3. PRICED KILL — every BUY ends with K:<price>;D:<%>, where K is a numeric dollar price equal to the higher of (20d MA level or stated support, current price × 0.97). D ≤3% full size, ≤6% half size, >6% pass. On the first cycle where a holding’s supplied current price is ≤ K, issue a full SELL for that ticker before evaluating any HOLD or new BUY; no confirmation, fresh-entry grace, averaging, or waiting for a close may override it. A holding without a numeric K price uses cost × 0.97. Falsified if the next 20 K-breach exits average a realized loss worse than −3.5%.