---
id: DA.ltm.29
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "2. QUARANTINE — If ticker is on the QUARANTINE line → PASS; otherwise…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 36
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#29
sep_before: ""
sep_after: ""
body_sha256: d5477b7cb9ef7d44fe0b0e495ca8545a17b9313c0b87a8fac9f3b4854abd0170
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-10T17:31:57.824077
row_updated_at: 2026-10-28T14:45:32.204916
injected: false
active: false
---
- [rule] 2. QUARANTINE — If ticker is on the QUARANTINE line → PASS; otherwise next gate. Falsified if the next 20 post-quarantine same-ticker campaigns average ≤-1.86%.