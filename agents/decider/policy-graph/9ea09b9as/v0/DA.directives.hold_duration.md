---
id: DA.directives.hold_duration
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "HOLD DURATION AWARENESS"
node_type: section
polarity: action
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#547
sep_before: ""
sep_after: "\n\n"
body_sha256: 96efa76ab423752b6a5dbf672933b708ace49a9db14b8abaf7a97acd15331228
tags: []
tickers: []
---
HOLD DURATION AWARENESS
- Use each holding’s purchase timestamp to judge staleness; mention “held Xd” in the reason when deciding to hold/sell.
- If a position has been held beyond the 1–5 day swing window without a fresh catalyst, bias to trim/exit and state that the trade is stale.