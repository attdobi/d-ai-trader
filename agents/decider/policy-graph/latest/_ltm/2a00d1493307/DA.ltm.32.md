---
id: DA.ltm.32
version: ltm@2a00d1493307
agent: DeciderAgent
title: "#priced-kill-gate — 1. PRICED KILL — IF K:/D: has no D:% number THEN…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 25
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#32
sep_before: ""
sep_after: ""
body_sha256: 9d3ebc6f49a5bc27dcafd23a2cd544acf79fde6fb4cdfd52dd44a293a229265d
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-24T17:32:43.612718
row_updated_at: 2026-09-24T17:32:43.612718
injected: false
active: true
---
- [rule] #priced-kill-gate — 1. PRICED KILL — IF K:/D: has no D:% number THEN pass. Otherwise next gate. Falsified if the next 20 numeric-D entries average below -2.03%.