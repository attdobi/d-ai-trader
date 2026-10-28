---
id: DA.ltm.42
version: ltm@2a00d1493307
agent: DeciderAgent
title: "3. EVENT — IF EVENT CALENDAR for a new BUY shows MACRO WINDOW flag 1…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 15
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#42
sep_before: ""
sep_after: ""
body_sha256: b4197810d45907b255d1d78d9385a71d25141595e4830182220775264b08b24f
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-22T17:32:15.699913
row_updated_at: 2026-10-22T17:32:15.699913
injected: true
active: true
---
- [rule] 3. EVENT — IF EVENT CALENDAR for a new BUY shows MACRO WINDOW flag 1 THEN pass. Otherwise next gate. Falsified if 20 passed rows tracked as shadow trades average above +1% over 5 sessions.