---
id: DA.directives.core_rules.n2
version: DeciderAgent.9ea09b9as.v6
agent: DeciderAgent
title: "Treat inherited/synced positions as untrusted inventory. Rec"
node_type: rule
polarity: caution
polarity_source: heuristic
parent: DA.directives.core_rules
field: strategy_directives
order: 5
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#565
sep_before: ""
sep_after: "\n"
body_sha256: 36ef52c280ad3b369cc9d59b49043333f261646fdd56b093c2ab0467b477a67b
tags: []
tickers: []
---
2. Treat inherited/synced positions as untrusted inventory. Reconstruct a hold thesis from current data; if unavailable, assume no validated entry edge.