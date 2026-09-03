---
id: FA.memory.log.2026_06_20
version: FeedbackAgent.9ea09b9as.v4
agent: FeedbackAgent
title: 2026-06-20
node_type: entry
polarity: gate
polarity_source: heuristic
parent: FA.memory
field: memory
order: 1
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#569
sep_before: ""
sep_after: "\n\n"
body_sha256: b160ed340019bcd4d9b3c3bad37cdeb7ec7a815cc347f785ff994beeca3a2ff9
tags: [process, position-state, summarizer, risk, memory, anti-hallucination]
tickers: []
---
## 2026-06-20
- [[Synced positions]] are inventory, not alpha. Repeated buy_reasoning of "Schwab synced position" means entry quality is unknown; Feedback must force Decider to triage, not validate. #process #position-state
- [[Catalyst freshness]] remains the dominant failure mode. Headlines must be tagged fresh, stale, failed, or absent, then checked against VWAP, 10m trend, abnormal volume, and SPY/sector [[relative strength]]. #summarizer
- [[Failed catalyst]] losers such as weak tape after bullish narratives must be cut earlier. Do not let stale/no-catalyst holdings drift to -6% to -8%; flag -2% plus below-VWAP/weak-10m as a kill-zone candidate when owned. #risk
- Feedback snippets must be short, deterministic, and executable. Prefer one high-impact rule over broad advice. #memory
- Maintain [[portfolio state integrity]]: HOLD/SELL only applies to confirmed owned tickers; cash-only portfolios require BUY candidates or a cash_reason. Never invent holdings. #anti-hallucination