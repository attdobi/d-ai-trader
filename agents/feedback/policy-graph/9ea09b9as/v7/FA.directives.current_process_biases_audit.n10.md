---
id: FA.directives.current_process_biases_audit.n10
version: FeedbackAgent.9ea09b9as.v7
agent: FeedbackAgent
title: "If all observed buys are synced/inherited, do not evaluate t"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 13
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#598
sep_before: ""
sep_after: "\n"
body_sha256: 973562b23e427636acd14e1292708ac97dacac6fe31b65cdda852e46dd299c1f
tags: []
tickers: []
---
10. If all observed buys are synced/inherited, do not evaluate them as entry alpha. Evaluate only cleanup, triage, and exit discipline unless true new-entry evidence exists.