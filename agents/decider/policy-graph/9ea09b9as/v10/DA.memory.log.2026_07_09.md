---
id: DA.memory.log.2026_07_09
version: DeciderAgent.9ea09b9as.v10
agent: DeciderAgent
title: 2026-07-09
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#575
sep_before: ""
sep_after: ""
body_sha256: 90d84cc0f82ae0d49a2084bf607c4c2d2486932fb706abdf208b87aa1f03376e
tags: []
tickers: []
---
## 2026-07-09
Separate true alpha trades from synced inventory. Recent alpha-style pullback trades were roughly positive, while synced/inherited positions were a major expectancy leak. Synced losers such as COIN -5.2%, CMG -3.4%, LOW -3.9%, INTC -2.6%, WBD -1.3%, and CC -1.6% show that inherited positions without fresh confirmation should be quarantined, not rationalized. Rule: synced positions may only be held if catalyst is fresh, price is above VWAP, 10-minute trend is positive, RS is positive, and loss...