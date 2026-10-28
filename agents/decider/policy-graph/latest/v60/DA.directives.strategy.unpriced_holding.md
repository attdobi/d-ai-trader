---
id: DA.directives.strategy.unpriced_holding
version: DeciderAgent.9ea09b9as.v60
agent: DeciderAgent
title: "UNPRICED HOLDING"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 14
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#664
sep_before: ""
sep_after: "\n\n"
body_sha256: dfb44134f03935ab403b1d310644f95b4dd45a2df7a59b2d62458c95ab2f0855
tags: []
tickers: []
---
12. UNPRICED HOLDING — Fully SELL a confirmed holding whose supplied buy reason lacks an executable numeric K:<price>;D:<%> record. This rule takes priority over the old cost × 0.97 fallback. Do not invent a missing entry kill from memory.