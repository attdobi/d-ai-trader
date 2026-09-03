---
id: DA.memory.log.2026_06_20_ground_truth
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "2026-06-20 #ground-truth #anti-hallucination"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n\n"
body_sha256: c39ebfbe0741e604d71e824637662aedccff20e684ea4ff1f36d3d6d62c4a568
tags: [ground-truth, anti-hallucination]
tickers: []
---
## 2026-06-20 #ground-truth #anti-hallucination
- **Setup:** Decider outputs must reflect actual holdings, not watchlists, summaries, or prior memory.
- **Outcome:** Invalid HOLD/SELL actions would create execution errors and false portfolio reasoning.
- **Root cause:** Summaries and headlines can mention tickers that are not owned.
- **Adjustment:** Build a holdings set first; SELL/HOLD only if ticker appears in Holdings. Cash-only portfolios may only BUY or give cash_reason.
- **Related:** [[portfolio-state]], [[execution-safety]]