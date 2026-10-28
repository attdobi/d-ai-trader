---
id: DA.ltm.25
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "2. QUARANTINE — If the ticker appears on the QUARANTINE line, PASS; o…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 40
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#25
sep_before: ""
sep_after: ""
body_sha256: 7f82c8211dce56ee5aed202eb9595ac077bebe4e13b5204146567d74e7c8a37f
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-03T17:32:56.597480
row_updated_at: 2026-10-28T14:45:32.204916
injected: false
active: false
---
- [rule] 2. QUARANTINE — If the ticker appears on the QUARANTINE line, PASS; otherwise fall through. Falsified if the next 20 tracked quarantined signals average >+1.0% over 1-5 days.