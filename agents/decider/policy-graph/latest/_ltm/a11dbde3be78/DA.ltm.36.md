---
id: DA.ltm.36
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "3. REGIME SIZE — IF INDEX REGIME is MIXED or RISK-OFF THEN half size.…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 29
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#36
sep_before: ""
sep_after: ""
body_sha256: 561525e063c09e46d9d58375573c189cf383cca94383a935f9fd913e387559e9
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-01T17:32:08.835641
row_updated_at: 2026-10-28T14:45:32.204916
injected: false
active: false
---
- [rule] 3. REGIME SIZE — IF INDEX REGIME is MIXED or RISK-OFF THEN half size. Otherwise next gate. Falsified if the next 20 such entries average above +1.00%.