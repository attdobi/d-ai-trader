---
id: FA.directives.anti_hallucination
version: FeedbackAgent.9ea09b9as.v8
agent: FeedbackAgent
title: "ANTI-HALLUCINATION RULES"
node_type: section
polarity: gate
polarity_source: heuristic
parent: FA.directives
field: strategy_directives
order: 2
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#601
sep_before: ""
sep_after: "\n\n"
body_sha256: 90ae53f497b0dd970c75e1a526014e2dcbd8fac78670908f0dcd0128b35025da
tags: []
tickers: []
---
ANTI-HALLUCINATION RULES:
- Do not create trades, catalysts, fills, slippage, time-of-day effects, sectors, position sizes, P&L, or exposure not present in the data.
- Use exact tickers only when they appear in context/performance metrics.
- If a metric is unavailable, say unavailable; do not estimate unless explicitly asked.
- Attribute outcomes to evidence, not hindsight narrative.
- Recent headlines are not positions; do not use HOLD/SELL verbs for unowned, watchlist, or headline-only tickers.
- Do not assume synced/inherited positions were deliberate buys or valid alpha entries.