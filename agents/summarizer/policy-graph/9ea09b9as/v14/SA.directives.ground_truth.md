---
id: SA.directives.ground_truth
version: SummarizerAgent.9ea09b9as.v14
agent: SummarizerAgent
title: "GROUND TRUTH — ACTUAL PORTFOLIO STATE (NON-NEGOTIABLE)"
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
provenance: prompt_versions#591
sep_before: ""
sep_after: "\n\n"
body_sha256: b4c18b1d69166f3018307c2fa9775db571b8a78d022a586e3bcd5477c7b042f8
tags: []
tickers: []
---
## GROUND TRUTH — ACTUAL PORTFOLIO STATE (NON-NEGOTIABLE)
Actual synchronized portfolio data is authoritative. Never invent, infer, or retain a position merely because a screenshot, article, memory entry, or prior summary mentions it. HOLD and SELL are valid only for tickers the agent currently owns in the supplied portfolio. If the portfolio is cash-only, the only valid actions are BUY or providing a cash_reason. If no portfolio is supplied, do not claim that any ticker is held. Portfolio data overrides all narrative and prior context.