---
id: DA.directives.core_rules.n8
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "Default reject BUYs that are headline-only, stale, obvious m"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n"
body_sha256: 6ae3df87682ca4412844bb57c5800f1128ad5bfe464066fd547a4b4ae308c931
tags: []
tickers: []
---
8. Default reject BUYs that are headline-only, stale, obvious media hype, ATH chases, weak 10m tape, below VWAP, near intraday lows, sector-relative laggards, or missing confirmation data.