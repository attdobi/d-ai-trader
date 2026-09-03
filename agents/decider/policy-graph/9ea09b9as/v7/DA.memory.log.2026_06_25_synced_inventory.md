---
id: DA.memory.log.2026_06_25_synced_inventory
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "2026-06-25 #synced-inventory #early-exit"
node_type: entry
polarity: evidence
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 12
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n\n"
body_sha256: 6e4eb70b3d17be12cb1c17d6d31cf548dad8a983fb6e94fe5e32b48eaaaf49bf
tags: [synced-inventory, early-exit]
tickers: []
---
## 2026-06-25 #synced-inventory #early-exit
- **Setup:** Latest feedback again shows inherited [[Schwab-synced-position]] inventory dominated the sample and entry alpha remains unvalidated.
- **Outcome:** Success rate stayed near 25% with average return around -0.89%, meaning exits and risk control must carry expectancy.
- **Root cause:** Weak synced holdings were sometimes defended too long with stale narratives instead of current demand.
- **Adjustment:** For synced positions down >1.0–1.5% with below-VWAP/weak 10m trend or negative sector relative strength, cut full/majority.
- **Related:** [[inventory-triage]], [[loss-containment]], [[vwap]]