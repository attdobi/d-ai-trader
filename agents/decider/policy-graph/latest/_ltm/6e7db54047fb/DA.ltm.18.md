---
id: DA.ltm.18
version: ltm@6e7db54047fb
agent: DeciderAgent
title: "REGIME GATE (read the INDEX REGIME line first): RISK-ON = up to 3 new…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 4
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#18
sep_before: ""
sep_after: ""
body_sha256: af9d3b408c5c5de6541eaf33b1512cb87fa1bcf507ac7ee379ce303978168b87
tags: [regime]
tickers: []
kind: rule
source: human
weight: 2.0
ticker: null
row_created_at: 2026-09-02T14:57:20.874602
row_updated_at: 2026-09-02T14:57:20.874602
injected: true
active: true
---
- [rule] REGIME GATE (read the INDEX REGIME line first): RISK-ON = up to 3 new BUYs at full rails. MIXED = at most 2 new BUYs at half size, extension ≤5%. RISK-OFF = cash is the default, at most 1 half-size BUY (oversold reversal or ≤3% above the 20d MA), harvest at +2%. Cash in RISK-OFF is discipline, not failure.