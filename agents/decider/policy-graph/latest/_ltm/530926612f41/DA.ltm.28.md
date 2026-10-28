---
id: DA.ltm.28
version: ltm@530926612f41
agent: DeciderAgent
title: "1. PRICED KILL — If proposed K:/D: is not numeric with D≤2.3% → PASS;…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 29
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#28
sep_before: ""
sep_after: ""
body_sha256: c921e9591b40463f7e5408dcf8b230134f7231f57face354019a76dd0816eb52
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-10T17:31:57.819986
row_updated_at: 2026-09-10T17:31:57.819986
injected: false
active: true
---
- [rule] 1. PRICED KILL — If proposed K:/D: is not numeric with D≤2.3% → PASS; otherwise next gate. Falsified if losers among the next 20 compliant campaigns average worse than -2.38%.