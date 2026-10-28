---
id: DA.directives.strategy.candidates
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: CANDIDATES
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 10
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: 355df06dd7f95323ee21542e219124a3bec18d71cababc9182a6ff23aceee301
tags: []
tickers: []
---
8. CANDIDATES — Weigh at least 2 candidates before a new BUY, normally the best 2–3 supplied names. If fewer than 2 were actually assessed, do not initiate a BUY; explain the coverage limitation. Rank accepted entries R1..Rk. This audit minimum never forces a fabricated candidate or a trade.