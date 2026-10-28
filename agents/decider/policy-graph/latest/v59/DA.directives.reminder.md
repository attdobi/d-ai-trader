---
id: DA.directives.reminder
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: "Latest Feedback Reminder (2026-10-22)"
node_type: reminder
polarity: caution
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 15
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n\n"
body_sha256: 1d320d2b23388e46693690cf4aefff222e26bce95346fcc73465169d8e852a77
tags: []
tickers: []
---
## Latest Feedback Reminder (2026-10-22)
- 1. LOSS CAP — IF a confirmed Holding shows P&L of -0.8% or worse THEN SELL. Otherwise next gate. Falsified if 20 triggered exits have a mean 5-session return above +1% from sale.
- 2. KILL BREACH — IF a confirmed Holding is $0.01 or more below its K: price THEN SELL. Otherwise next gate. Falsified if 20 exits have a mean 5-session return above +1% from sale.
- 3. EVENT SIZE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN allow at most 1 half-size BUY under D≤1.3%, earnings, quarantine, setup and cash gates. Otherwise next gate. Falsified if 20 compliant entries average below 0%.