---
id: FA.directives.current_process_biases_audit.n11
version: FeedbackAgent.9ea09b9as.v5
agent: FeedbackAgent
title: "Low-expectancy loss gate: for confirmed owned synced/inherit"
node_type: rule
polarity: mixed
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 14
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#582
sep_before: ""
sep_after: "\n"
body_sha256: 3f6aa87e8a8ad953785f5ae8c95272d64e59aabe53f2443823f8f86d39dbddcc
tags: []
tickers: []
---
11. Low-expectancy loss gate: for confirmed owned synced/inherited positions with stale, failed, absent, or fresh_unconfirmed catalysts plus below-VWAP, weak 10m trend, or negative RS, Feedback should push Decider to reduce or exit before losses reach -1.5% to -2%, not wait for -6% to -8%.