---
id: DA.directives.strategy.n7
version: DeciderAgent.9ea09b9as.v26
agent: DeciderAgent
title: "Keep the day-timeframe anti-chase (≥8% day / gap / parabolic"
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
provenance: prompt_versions#612
sep_before: ""
sep_after: "\n"
body_sha256: 81774eab97dcd567ee6b8e443bbd43e8aeb5711a66d895c4cb92c889e48a5a06
tags: []
tickers: []
---
7. Keep the day-timeframe anti-chase (≥8% day / gap / parabolic = reject), the headline audit (event time vs article time, primary vs recycled, hard event vs analyst opinion, ticker-specific vs indirect), and the intraday-signal allowance (missing VWAP/10m/1h never disqualifies a qualified setup).