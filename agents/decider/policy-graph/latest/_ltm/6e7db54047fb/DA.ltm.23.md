---
id: DA.ltm.23
version: ltm@6e7db54047fb
agent: DeciderAgent
title: "DEPLOY when the regime allows: in RISK-ON take the best 1-3 non-exten…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 9
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#23
sep_before: ""
sep_after: ""
body_sha256: 38ffc0b282d53b5182075b1fd1a653008b99709379f4fa75709bccec7359c8a2
tags: [deploy, regime]
tickers: []
kind: rule
source: human
weight: 1.5
ticker: null
row_created_at: 2026-09-02T14:57:20.877385
row_updated_at: 2026-09-02T14:57:20.877385
injected: true
active: true
---
- [rule] DEPLOY when the regime allows: in RISK-ON take the best 1-3 non-extended watchlist setups rather than sitting in cash; in RISK-OFF cash is the correct default (≤1 half-size BUY). Never deploy because cash 'feels like failure'.