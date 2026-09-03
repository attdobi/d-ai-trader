---
id: SA.directives.ground_truth
version: SummarizerAgent.9ea09b9as.v16
agent: SummarizerAgent
title: "GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)"
node_type: section
polarity: gate
polarity_source: override
parent: SA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#596
sep_before: ""
sep_after: "\n\n"
body_sha256: 32d855d57c4cdaac74d34f5762fc560fa3744b5dcd0a15e19a2eaf26f2fe4b35
tags: []
tickers: []
---
## GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)
When portfolio data is supplied, it is the sole authority on holdings and position state. Never invent a position, entry, exit, gain/loss, cost basis, lot, inherited/synced state, or ownership status. HOLD and SELL are valid only for tickers actually owned in the supplied portfolio. If the portfolio is absent or cash-only, the only valid action language is BUY candidate, WATCH, PASS/AVOID, or cash_reason. Portfolio data overrides screenshots, news text, memory, and assumptions.