---
id: DA.directives.core_rules.n6
version: DeciderAgent.9ea09b9as.v6
agent: DeciderAgent
title: "Default reject BUYs that are headline-only, stale, obvious m"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 9
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#565
sep_before: ""
sep_after: "\n"
body_sha256: 5082eac0be4c85e28d7f8f29a9447b81c1ee818541b562636b70c694e8be2323
tags: []
tickers: []
---
6. Default reject BUYs that are headline-only, stale, obvious media hype, ATH chases, weak 10m tape, below VWAP, near intraday lows, or sector-relative laggards.