---
id: DA.ltm.24
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise f…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 41
owner: decider_memory
status: inactive
compiled: never
locked: true
provenance: decider_memory#24
sep_before: ""
sep_after: ""
body_sha256: b20f8c4029d28ea66c24d7077a2a407ffb184c3397d77905a8be721d47649142
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-03T17:32:56.594134
row_updated_at: 2026-10-28T09:38:30.469921
injected: false
active: false
---
- [rule] 1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise fall through. Falsified if the next 20 tracked RISK-OFF candidates average >+1.0% over 1-5 days.