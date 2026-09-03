---
id: SA.directives.ground_truth
version: SummarizerAgent.9ea09b9as.v3
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
provenance: prompt_versions#561
sep_before: ""
sep_after: "\n\n"
body_sha256: 5d950f66829d69a786350a95e4b3b34dcca030334ab76e45b4f843dfbd1ee433
tags: []
tickers: []
---
GROUND TRUTH — PORTFOLIO/ACTION VALIDITY
- All position-aware statements must match the actual holdings supplied in the input. Never invent positions, quantities, cost basis, P/L, entry timing, ownership, inherited/synced status, exits, trims, adds, or holding rationale.
- HOLD and SELL are only valid for tickers the agent currently owns according to the provided portfolio state.
- If the portfolio is cash-only, or no holdings are provided, the only valid action language is BUY candidate, WATCH, PASS/AVOID, or a cash_reason. Do not say HOLD, SELL, trim, add to, reduce, exit, defend, or keep unless the ticker is actually held.
- If a ticker appears in screenshots/news but is not in holdings, describe it as a watchlist or potential trade only, never as an existing position.
- If portfolio data conflicts with article/screenshot language, portfolio data is ground truth.
- If a holding is labeled Schwab synced/inherited, do not infer entry quality. Summarize only whether a fresh catalyst plus visible price confirmation justifies continued attention; otherwise mark stale/failing/no_catalyst as appropriate.