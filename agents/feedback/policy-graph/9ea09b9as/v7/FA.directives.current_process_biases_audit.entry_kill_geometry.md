---
id: FA.directives.current_process_biases_audit.entry_kill_geometry
version: FeedbackAgent.9ea09b9as.v7
agent: FeedbackAgent
title: "ENTRY KILL GEOMETRY"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 19
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#598
sep_before: ""
sep_after: ""
body_sha256: 44c81e4568bb84159bd002a008748f6a90625537a5f043fe1dae73977fe2e439
tags: []
tickers: []
---
16. ENTRY KILL GEOMETRY: For every proposed new BUY, Summarizer must surface the numeric entry-time kill price and percentage distance from entry when the supplied data permits; otherwise mark kill geometry unavailable. Decider must not open a new position when its only invalidation is an unpriced moving-average reference. This requirement concerns new BUYs only and never implies an action for an unconfirmed holding.