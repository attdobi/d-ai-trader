---
id: DA.memory.log.2026_10_22
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: 2026-10-22
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory
field: memory
order: 14
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#661
sep_before: ""
sep_after: "\n\n"
body_sha256: b3287e4af9be548ce05952eb2945eaa09363ec33ccce609a151f4985c22ec5fa
tags: []
tickers: []
---
## 2026-10-22
- 1. LOSS CAP — IF a confirmed Holding shows P&L of -0.8% or worse THEN SELL. Otherwise next gate. Falsified if 20 triggered exits have a mean 5-session return above +1% from sale.
- 2. KILL BREACH — IF a confirmed Holding is $0.01 or more below its K: price THEN SELL. Otherwise next gate. Falsified if 20 exits have a mean 5-session return above +1% from sale.
- 3. EVENT SIZE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN allow at most 1 half-size BUY under D≤1.3%, earnings, quarantine, setup and cash gates. Otherwise next gate. Falsified if 20 compliant entries average below 0%.