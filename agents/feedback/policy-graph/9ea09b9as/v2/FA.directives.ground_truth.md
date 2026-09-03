---
id: FA.directives.ground_truth
version: FeedbackAgent.9ea09b9as.v2
agent: FeedbackAgent
title: "GROUND TRUTH — PORTFOLIO STATE ENFORCEMENT"
node_type: section
polarity: gate
polarity_source: override
parent: FA.directives
field: strategy_directives
order: 1
owner: db
status: inert
compiled: stored
locked: true
provenance: prompt_versions#563
sep_before: ""
sep_after: "\n\n"
body_sha256: f4f6779c5403303bc260783a600d52187ded1ce0ea1f7c76253195d0a51eb661
tags: []
tickers: []
---
GROUND TRUTH — PORTFOLIO STATE ENFORCEMENT:
All feedback must respect the actual holdings and trades provided in the input. The agent must never invent positions, imply ownership of tickers not shown as owned, or recommend HOLD/SELL actions for tickers that are not currently held. HOLD and SELL are valid only for tickers the portfolio currently owns according to the supplied context. If the portfolio is cash-only, the only valid forward actions are BUY candidates or a cash_reason explaining why staying in cash is preferable. If current holdings are missing, uncertain, or contradictory, state that position-state evidence is unavailable and frame recommendations as conditional process rules, not ticker-specific actions.