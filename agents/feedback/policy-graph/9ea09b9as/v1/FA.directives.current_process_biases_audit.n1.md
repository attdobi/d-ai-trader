---
id: FA.directives.current_process_biases_audit.n1
version: FeedbackAgent.9ea09b9as.v1
agent: FeedbackAgent
title: "Synced/inherited positions are inventory, not validated buys"
node_type: rule
polarity: mixed
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 4
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#560
sep_before: ""
sep_after: "\n"
body_sha256: 978e2fda2b020ac59e3a147ca7738fe8dbcc8371341c98d96607ad4c5338828e
tags: []
tickers: []
---
1. Synced/inherited positions are inventory, not validated buys. Feedback must call out when buy_reasoning is merely account synchronization and should not be treated as alpha evidence.