---
id: DA.ltm.38
version: ltm@2a00d1493307
agent: DeciderAgent
title: "1. KILL — IF a confirmed Holding's current price is below its buy-rea…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 19
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#38
sep_before: ""
sep_after: ""
body_sha256: 81388398318c11ca0a1e8fa27a65af045d943adbcf6a0db73685551b1a2088e4
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-15T17:31:32.448702
row_updated_at: 2026-10-15T17:31:32.448702
injected: false
active: true
---
- [rule] 1. KILL — IF a confirmed Holding's current price is below its buy-reason K: price THEN SELL. Otherwise next gate. Falsified if 20 such exits have average next-session return above +1%.