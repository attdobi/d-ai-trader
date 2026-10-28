---
id: DA.directives.strategy.event_gate
version: DeciderAgent.9ea09b9as.v59
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
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n"
body_sha256: f72adf2f76f954e25b519b2a04f752d37c8dfc263b48fffe64fb0bceb67f8b6a
tags: []
tickers: []
---
9. EVENT GATE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN allow at most 1 half-size BUY under D≤1.3%, earnings, quarantine, setup and cash gates. Otherwise next gate. Falsified if 20 compliant entries average below 0%.