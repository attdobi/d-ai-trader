---
id: DA.directives.strategy.re_entry_quarantine
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "RE-ENTRY QUARANTINE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: dbb2dc97096329084733d887825d7d9819471e062470d329ca152688fa1d77be
tags: []
tickers: []
---
4. RE-ENTRY QUARANTINE — IF the ticker is on the QUARANTINE line or was exited within 2 sessions THEN no BUY. Otherwise next gate. Falsified if 15 quarantined names would have averaged better than +1% over the next 3 sessions.