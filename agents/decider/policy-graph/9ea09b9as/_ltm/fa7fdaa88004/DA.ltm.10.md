---
id: DA.ltm.10
version: ltm@fa7fdaa88004
agent: DeciderAgent
title: "Separate true alpha trades from synced inventory. Recent alpha-style…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 15
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#10
sep_before: ""
sep_after: ""
body_sha256: 5a1c24a2099e4bd8649ee6f45e3b6073b690288abe0ae6fc20918f00d3136b42
tags: []
tickers: []
kind: lesson
source: feedback
weight: 1.2
ticker: null
row_created_at: 2026-07-09T17:31:06.065829
row_updated_at: 2026-09-02T14:57:20.873014
injected: false
active: false
---
- [lesson] Separate true alpha trades from synced inventory. Recent alpha-style pullback trades were roughly positive, while synced/inherited positions were a major expectancy leak. Synced losers such as COIN -5.2%, CMG -3.4%, LOW -3.9%, INTC -2.6%, WBD -1.3%, and CC -1.6% show that inherited positions without fresh confirmation should be quarantined, not rationalized. Rule: synced positions may only be held if catalyst is fresh, price is above VWAP, 10-minute trend is positive, RS is positive, and loss...