---
id: DA.directives.strategy.event_gate
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "EVENT GATE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: 1a570c7d40e6fe13e16176d7812d9b26b57af0440cdd07f0d360504a399c179d
tags: []
tickers: []
---
9. EVENT GATE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN pass. Otherwise next gate. Falsified if 20 candidates passed by this gate average above +1% over their next 5 sessions.