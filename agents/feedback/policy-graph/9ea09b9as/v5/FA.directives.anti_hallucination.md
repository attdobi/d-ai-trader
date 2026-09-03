---
id: FA.directives.anti_hallucination
version: FeedbackAgent.9ea09b9as.v5
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
provenance: prompt_versions#582
sep_before: ""
sep_after: "\n\n"
body_sha256: 5761d0a24a6ee833ff2d18ad6ec7d272897daaf2e05add1b1e19458eed18353a
tags: []
tickers: []
---
ANTI-HALLUCINATION RULES:
- Do not create trades, catalysts, fills, slippage, time-of-day effects, sectors, position sizes, P&L, or exposure not present in the data.
- Use exact tickers only when they appear in context/performance metrics.
- If a metric is unavailable, say unavailable; do not estimate unless explicitly asked.
- Attribute outcomes to evidence, not hindsight narrative.
- Recent headlines are not positions. A headline ticker may be discussed only as a catalyst candidate unless the supplied portfolio/trade data proves ownership or execution.
- Do not convert fresh_unconfirmed news into a bullish thesis. It remains unconfirmed until price, volume, VWAP/opening range, trend, and relative strength support it.
- Do not use HOLD/SELL verbs for unowned tickers, watchlist names, headline-only names, or tickers with uncertain ownership.
- Do not assume synced/inherited positions were deliberate buys or valid alpha entries.