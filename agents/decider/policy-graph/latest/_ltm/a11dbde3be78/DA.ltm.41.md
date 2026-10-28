---
id: DA.ltm.41
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "2. KILL BREACH — IF a confirmed Holding is $0.01 or more below its K:…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 24
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#41
sep_before: ""
sep_after: ""
body_sha256: 41ead4fdee82e6e93964c003286ddbdcf1272fb18dc2436030f145d0a91ab378
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-22T17:32:15.694988
row_updated_at: 2026-10-28T14:45:32.204916
injected: false
active: false
---
- [rule] 2. KILL BREACH — IF a confirmed Holding is $0.01 or more below its K: price THEN SELL. Otherwise next gate. Falsified if 20 exits have a mean 5-session return above +1% from sale.