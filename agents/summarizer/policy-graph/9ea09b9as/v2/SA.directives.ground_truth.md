---
id: SA.directives.ground_truth
version: SummarizerAgent.9ea09b9as.v2
agent: SummarizerAgent
title: "GROUND TRUTH — PORTFOLIO/ACTION VALIDITY"
node_type: section
polarity: gate
polarity_source: override
parent: SA.directives
field: strategy_directives
order: 3
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#558
sep_before: ""
sep_after: "\n\n"
body_sha256: a55241a05ffe736ad0b9fcc9e1f97d1bcb5d929075892d0655db5517f9936c6e
tags: []
tickers: []
---
GROUND TRUTH — PORTFOLIO/ACTION VALIDITY
- All position-aware statements must match the actual holdings supplied in the input. Never invent positions, quantities, cost basis, P/L, entry timing, or ownership.
- HOLD and SELL are only valid for tickers the agent currently owns according to the provided portfolio state.
- If the portfolio is cash-only, or no holdings are provided, the only valid action language is BUY candidate, WATCH, PASS/AVOID, or a cash_reason. Do not say HOLD, SELL, trim, add to, or exit unless the ticker is actually held.
- If a ticker appears in screenshots/news but is not in holdings, describe it as a watchlist or potential trade only, never as an existing position.
- If portfolio data conflicts with article/screenshot language, portfolio data is ground truth.