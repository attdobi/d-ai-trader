---
id: DA.memory.log.2026_06_24_loss_containment
version: DeciderAgent.9ea09b9as.v5
agent: DeciderAgent
title: "2026-06-24 #loss-containment #vwap"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 10
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#562
sep_before: ""
sep_after: "\n\n"
body_sha256: 15d6ce21ba44f3ddd9a1c096b4b444476300bf649e2101ad45c1495a0863f2eb
tags: [loss-containment, vwap]
tickers: [BA, CME, NVDA, USO]
---
## 2026-06-24 #loss-containment #vwap
- **Setup:** Weak holdings with stale catalysts repeatedly performed poorly when below VWAP, near lows, or lacking 10m trend support.
- **Outcome:** Losses became larger than winners when exits waited for deeper confirmation of failure.
- **Root cause:** The process tolerated down >2% positions without demanding fresh reversal evidence.
- **Adjustment:** If owned, down >2%, stale/no catalyst, and weak tape, sell full or at least majority immediately; do not wait for -6% to -8%.
- **Related:** [[NVDA]], [[USO]], [[BA]], [[CME]], [[failed-catalyst]]