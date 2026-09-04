---
id: DA.ltm.20
version: ltm@6e7db54047fb
agent: DeciderAgent
title: "PRICED KILL: every BUY reason ends with K:<price>;D:<%> — K = the hig…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 2
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#20
sep_before: ""
sep_after: ""
body_sha256: 14b00aafe3faed024453098b13a11bcd65ee8df2fc27d1cbf508d3fe5aa8bdcd
tags: [kill, risk]
tickers: []
kind: rule
source: human
weight: 2.0
ticker: null
row_created_at: 2026-09-02T14:57:20.876224
row_updated_at: 2026-09-02T14:57:20.876224
injected: true
active: true
---
- [rule] PRICED KILL: every BUY reason ends with K:<price>;D:<%> — K = the higher of (20d MA level or stated support, price × 0.97) from the watchlist numbers. D ≤3% full size, ≤6% half, >6% pass. Binding on the first breach, no widening; a holding without a K uses cost × 0.97. Unpriced '20d break' kills averaged -4.3% per loser vs -2.8% priced (Jul-Sep 2026).