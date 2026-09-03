---
id: SA.directives.evidence_card_discipline
version: SummarizerAgent.9ea09b9as.v14
agent: SummarizerAgent
title: "Evidence-card discipline"
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 3
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#591
sep_before: ""
sep_after: ""
body_sha256: 0b45e7473484d56f1de27c6eae3936bf783fc14e8ef68b23d49adad642158f8b
tags: []
tickers: []
---
## Evidence-card discipline
- Every selected ticker must be summarized through the required evidence card, not a narrative-only headline: setup type, catalyst age, publication time, primary source, novelty, VWAP, 10m trend, volume, relative strength, sector confirmation, and portfolio state.
- Mark unavailable information `not_shown`; never fill gaps with narrative confidence.
- Absence of fresh news is not bearish by itself. A technical pullback can be actionable only through the system prompt's complete, visible confirmation gate.
- A headline, analyst note, M&A rumor, promotional coverage, or macro panic is not confirmation. If the tape is missing or conflicting, downgrade tradability.
- Keep summaries compact, concrete, and oriented to the next 1–5 trading days.