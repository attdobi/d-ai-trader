---
id: DA.memory.log.2026_06_25_ground_truth
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "2026-06-25 #ground-truth #execution-safety"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 14
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n\n"
body_sha256: 85b20134149d7c2ca35d472ce009f1f13530c9d8c05dff32a7919fb0495d4c00
tags: [ground-truth, execution-safety]
tickers: []
---
## 2026-06-25 #ground-truth #execution-safety
- **Setup:** Portfolio actions must match actual Holdings exactly, even when summaries or memory mention familiar tickers.
- **Outcome:** Invalid HOLD/SELL outputs create execution risk and corrupt performance feedback.
- **Root cause:** Watchlist/news names can be mentally promoted into positions if the holdings set is not built first.
- **Adjustment:** Run final validation: every SELL/HOLD ticker must appear in Holdings; if cash-only, output only BUYs or cash_reason.
- **Related:** [[portfolio-state]], [[anti-hallucination]], [[execution-safety]]