---
id: SA.directives.selloff_evidence
version: SummarizerAgent.baseline.v0
agent: SummarizerAgent
title: "Selloff evidence"
node_type: section
polarity: mixed
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 7
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: ""
body_sha256: ed76ee563cf20eac65d755d10fe0bead9359f85a0ec001e91d4c3238078bce5b
tags: []
tickers: []
---
## Selloff evidence
When a source shows a sharp decline, put the ticker, price move, reference price or period, and observation time in insights when available. Distinguish a broad or sector selloff from company-specific news. Report visible evidence of stabilization or continued selling and identify its source. Leave missing baselines and causes unknown.