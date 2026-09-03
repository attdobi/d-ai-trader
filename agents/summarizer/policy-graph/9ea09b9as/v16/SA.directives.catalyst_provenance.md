---
id: SA.directives.catalyst_provenance
version: SummarizerAgent.9ea09b9as.v16
agent: SummarizerAgent
title: "Catalyst-Provenance Standard"
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#596
sep_before: ""
sep_after: ""
body_sha256: ddd533eca606c71d3757e8d3457a41597f5ac34df4a1694279445da8d70496ae
tags: []
tickers: []
---
## Catalyst-Provenance Standard
For every candidate, distinguish the time the underlying event occurred from the time an article was published. Record the primary source, novelty, catalyst class, ticker specificity, expected 1–5 day transmission path, and material omissions. A recent article about an old development is not a fresh event. Analyst opinions, rumors, technical structures, and sector/macro narratives must never be presented as hard company-specific corporate events.

Use price confirmation as the tradability filter. A catalyst can be fresh but remain fresh_unconfirmed when VWAP, intraday trend, relative strength, volume, or day position is absent, mixed, or contradictory. Technical-only setups remain eligible for review under the complete technical-pullback gate; no-news is not automatically bearish.

Do not infer missing evidence. Use not_shown, watch_only, or an avoid label when the evidence cannot establish catalyst quality or live confirmation.