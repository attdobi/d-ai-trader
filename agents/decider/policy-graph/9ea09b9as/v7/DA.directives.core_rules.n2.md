---
id: DA.directives.core_rules.n2
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "Reconcile repeated symbols, synced lots, and duplicate holdi"
node_type: rule
polarity: mixed
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 5
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n"
body_sha256: 7ec59974a5ff4839a7cf1cf4c50949016c37f9adc5aed77413fa2f13e44b8bd7
tags: []
tickers: []
---
2. Reconcile repeated symbols, synced lots, and duplicate holdings into one net ticker exposure before deciding. Output at most one net action per ticker.