---
id: DA.directives.core_rules.n10
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "Do not both buy and sell the same ticker in one cycle. If yo"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n"
body_sha256: ea1f3a6ed79459ddbab5f85ab7403c60c342f3f1ea071ea2f37fb19d1d9be1a9
tags: []
tickers: []
---
10. Do not both buy and sell the same ticker in one cycle. If you are reducing risk, sell/hold; if you are initiating, buy only if not already owned.