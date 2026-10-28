---
id: DA.ltm.31
version: ltm@2a00d1493307
agent: DeciderAgent
title: "2. PRICED KILL — IF the K:/D: line does not show a numeric D of 1.3%…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 26
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#31
sep_before: ""
sep_after: ""
body_sha256: 2d31e8ff342e4e57a93a5d6a23e67984a700dcd68f4a4d92ff34fd090091540a
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-17T17:33:33.489013
row_updated_at: 2026-09-17T17:33:33.489013
injected: false
active: true
---
- [rule] 2. PRICED KILL — IF the K:/D: line does not show a numeric D of 1.3% or less THEN pass. Otherwise next gate. Falsified if 20 compliant entries average below 0%.