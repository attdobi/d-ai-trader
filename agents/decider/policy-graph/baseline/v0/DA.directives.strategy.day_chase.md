---
id: DA.directives.strategy.day_chase
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "DAY CHASE"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 9
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: ac59a2bd11d4ca750af7250148cce31cb6381857caf8c5ccc39a72c0cd2ba48d
tags: []
tickers: []
---
7. DAY CHASE — Reject a new BUY after a day gain of 8% or more, a vertical gap or a parabolic spike. Green price action or proximity to a high alone does not establish a chase. Still apply the independent swing-extension cap.