---
id: DA.memory.log.2026_08_04_stop_execution
version: DeciderAgent.9ea09b9as.v14
agent: DeciderAgent
title: "2026-08-04 #stop-execution #risk-control"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 9
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#581
sep_before: ""
sep_after: ""
body_sha256: e03f6906de3602025641c76773bbf7acd4dc443968a6720ad8c707845b26dc2d
tags: [stop-execution, risk-control]
tickers: [TMO, ZS]
---
## 2026-08-04 #stop-execution #risk-control
- **Evidence:** [[ZS]] realized -4.9% after its entry reason stated a -2%/20d kill; [[TMO]] realized -4.8% after its stated -1.5%/20d exit.
- **Root cause:** Declared, setup-specific invalidation was not reflected in the eventual decision, allowing losses materially beyond the stated risk plan.
- **Adjustment:** Every new BUY records an objective `K:` criterion; when later data shows that criterion is met, exit rather than widening it. Do not convert this into an unsupported universal fixed stop.
- **Related:** [[loss-containment]] [[setup-specific-kill]]