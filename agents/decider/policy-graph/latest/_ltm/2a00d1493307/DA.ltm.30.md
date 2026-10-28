---
id: DA.ltm.30
version: ltm@2a00d1493307
agent: DeciderAgent
title: "1. FOMC EXIT — IF the EVENT CALENDAR shows the next FOMC decision lat…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 27
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#30
sep_before: ""
sep_after: ""
body_sha256: 804f5c817b235bd540723df5705b01ba7efe4352f28550a4ac038cd1e0182357
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-17T17:33:33.484286
row_updated_at: 2026-09-17T17:33:33.484286
injected: false
active: true
---
- [rule] 1. FOMC EXIT — IF the EVENT CALENDAR shows the next FOMC decision later today THEN SELL each confirmed Holding. Otherwise next gate. Falsified if 10 held-through-FOMC campaigns average above +1%.