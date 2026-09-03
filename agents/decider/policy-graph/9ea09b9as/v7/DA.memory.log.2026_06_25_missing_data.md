---
id: DA.memory.log.2026_06_25_missing_data
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "2026-06-25 #missing-data #entry-filter"
node_type: entry
polarity: caution
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 16
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: ""
body_sha256: 73f3cfb5d942c3d1c95e7f219e6c83b29ed7a2bb84276b4800618c62b54f1a2a
tags: [missing-data, entry-filter]
tickers: [BABA, BAYRY, MU]
---
## 2026-06-25 #missing-data #entry-filter
- **Setup:** Recent headlines included fresh_unconfirmed names such as [[BABA]] and [[BAYRY]], while [[MU]] was fresh but chase-prone after a visible surge.
- **Outcome:** News importance alone does not create edge when live VWAP, 10m trend, volume, and relative strength are absent or deteriorating.
- **Root cause:** The decider can treat missing confirmation as neutral instead of as failed evidence.
- **Adjustment:** Missing catalyst-age, VWAP, trend, volume, or relative-strength data counts as unconfirmed; choose cash over a forced headline buy.
- **Related:** [[headline-risk]], [[price-confirmation]], [[cash-is-a-position]]