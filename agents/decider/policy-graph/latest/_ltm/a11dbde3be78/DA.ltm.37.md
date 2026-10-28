---
id: DA.ltm.37
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "2. FOMC EXIT — IF EVENT CALENDAR shows FOMC is within 1 session THEN…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 28
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#37
sep_before: ""
sep_after: ""
body_sha256: 18f5ffc34b78dc2025973d940a472041244f5e152d8248eb7878cf6e36e8b805
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-10-08T17:31:57.680247
row_updated_at: 2026-10-28T14:45:32.204916
injected: false
active: false
---
- [rule] 2. FOMC EXIT — IF EVENT CALENDAR shows FOMC is within 1 session THEN SELL confirmed Holdings. Otherwise next gate. Falsified if the next 5 such exits forgo an average gain above 1% through the decision.