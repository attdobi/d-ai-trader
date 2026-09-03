---
id: DA.ltm.9
version: ltm@f3201f00e7d3
agent: DeciderAgent
title: "The system expectancy is negative: 21 trades, 23.8% positive, average…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 10
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#9
sep_before: ""
sep_after: ""
body_sha256: 2b6b0e4d7ea7cd9d5888b45bf86b21be1ac542e8dc9ae8d75c771c8b9ecc7119
tags: []
tickers: []
kind: lesson
source: feedback
weight: 1.2
ticker: null
row_created_at: 2026-07-02T17:31:22.438830
row_updated_at: 2026-09-02T14:57:20.873014
injected: false
active: false
---
- [lesson] The system expectancy is negative: 21 trades, 23.8% positive, average return -1.39%. The core leak is defending or inheriting inventory without fresh confirmed demand. First objective is quarantine synced positions. Synced inventory is not alpha; default action is reduce or exit unless it has fresh catalyst, above-VWAP tape, positive 10m trend, and sector confirmation. Hard rule: synced loser with no fresh catalyst and below/near VWAP gets cut by -0.75% to -1.5%; do not wait for -2% to -8%...