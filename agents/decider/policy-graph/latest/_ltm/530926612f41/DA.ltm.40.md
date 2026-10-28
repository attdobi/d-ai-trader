---
id: DA.ltm.40
version: ltm@530926612f41
agent: DeciderAgent
title: "1. LOSS CAP — IF a confirmed Holding shows P&L of -0.8% or worse THEN…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 17
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#40
sep_before: ""
sep_after: ""
body_sha256: 133a4544a63ffb8ba683ea94b6f728ebfa2706ecffbd29b2d0c5383229a0d065
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-22T17:32:15.692137
row_updated_at: 2026-10-22T17:32:15.692137
injected: false
active: true
---
- [rule] 1. LOSS CAP — IF a confirmed Holding shows P&L of -0.8% or worse THEN SELL. Otherwise next gate. Falsified if 20 triggered exits have a mean 5-session return above +1% from sale.