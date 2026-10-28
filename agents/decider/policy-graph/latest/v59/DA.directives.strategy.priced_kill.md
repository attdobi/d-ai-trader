---
id: DA.directives.strategy.priced_kill
version: DeciderAgent.9ea09b9as.v59
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
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n"
body_sha256: 024e63d18e5956fa4ae8c7f7f63679c5d97d27e3eb945ccc04a940dd4e3d0472
tags: []
tickers: []
---
3. PRICED KILL — IF the watchlist row lacks numeric K:<price>;D:<%> with D at or below 1.3% THEN pass. Otherwise next gate. Falsified if 20 rejected rows average above +1% over their next 5 sessions.