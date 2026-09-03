---
id: DA.directives.core_rules.n3
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "Treat inherited/synced positions as untrusted inventory. Rec"
node_type: rule
polarity: caution
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n"
body_sha256: 890d0c6e65c802d33776b5a39dffcacb0f94de809bd60aad86f29ef37af5f944
tags: []
tickers: []
---
3. Treat inherited/synced positions as untrusted inventory. Reconstruct a hold thesis from current data; if unavailable, assume no validated entry edge.