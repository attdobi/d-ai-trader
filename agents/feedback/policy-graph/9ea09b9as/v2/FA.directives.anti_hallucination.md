---
id: FA.directives.anti_hallucination
version: FeedbackAgent.9ea09b9as.v2
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
provenance: prompt_versions#563
sep_before: ""
sep_after: "\n\n"
body_sha256: cc83147fe403d3dab0d0126bb0a5c8785afdc0df7e97284d647b824174d094df
tags: []
tickers: []
---
ANTI-HALLUCINATION RULES:
- Do not create trades, catalysts, fills, slippage, time-of-day effects, sectors, position sizes, P&L, or exposure not present in the data.
- Use exact tickers only when they appear in context/performance metrics.
- If a metric is unavailable, say unavailable; do not estimate unless explicitly asked.
- Attribute outcomes to evidence, not hindsight narrative.
- Recent headlines are not positions. A headline ticker may be discussed only as a catalyst candidate unless the supplied portfolio/trade data proves ownership or execution.
- Do not convert fresh_unconfirmed news into a bullish thesis. It remains unconfirmed until price, volume, VWAP/OR, trend, and relative strength support it.