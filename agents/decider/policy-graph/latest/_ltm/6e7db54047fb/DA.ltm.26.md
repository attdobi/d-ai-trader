---
id: DA.ltm.26
version: ltm@6e7db54047fb
agent: DeciderAgent
title: "3. PRICED KILL — If the candidate K:/D: line is not numeric with 0<D≤…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 16
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#26
sep_before: ""
sep_after: ""
body_sha256: 6ee468fc0a342faf9a2403df1da85d9aeb92e9bfca5c85ba5b3524c9855d7fad
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-03T17:32:56.599366
row_updated_at: 2026-09-03T17:32:56.599366
injected: false
active: true
---
- [rule] 3. PRICED KILL — If the candidate K:/D: line is not numeric with 0<D≤2.4%, PASS; otherwise fall through. Falsified if the next 20 tracked rejects average >+1.0% over 1-5 days.