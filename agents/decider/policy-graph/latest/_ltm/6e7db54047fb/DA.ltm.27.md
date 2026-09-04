---
id: DA.ltm.27
version: ltm@6e7db54047fb
agent: DeciderAgent
title: "4. KILL BREACH — If a confirmed holding's current price is at/below i…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 15
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#27
sep_before: ""
sep_after: ""
body_sha256: 3c0437bbb36d10465500710c87e2fd55772b38c0c1b12d9226f4f804f7f3b982
tags: []
tickers: []
kind: rule
source: feedback
weight: 1.3
ticker: null
row_created_at: 2026-09-03T17:32:56.600828
row_updated_at: 2026-09-03T17:32:56.600828
injected: true
active: true
---
- [rule] 4. KILL BREACH — If a confirmed holding's current price is at/below its recorded K:, SELL; otherwise fall through. Falsified if the next 20 such breaches average >+1.0% over the following 1-5 days.