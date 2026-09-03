---
id: SA.memory.log.2026_06_24_portfolio_ground_truth
version: SummarizerAgent.9ea09b9as.v4
agent: SummarizerAgent
title: "2026-06-24 #portfolio-ground-truth #anti-hallucination"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: SA.memory.log
field: memory
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#564
sep_before: ""
sep_after: "\n\n"
body_sha256: 9ecd9515d8fa4936e580e529d9db313f3de5f5004e9adbe2ad429b2467782441
tags: [portfolio-ground-truth, anti-hallucination]
tickers: []
---
## 2026-06-24 #portfolio-ground-truth #anti-hallucination
- **Observation:** Summaries can contaminate downstream decisions if they imply HOLD/SELL/position context for tickers only seen in news screenshots.
- **Lesson:** Portfolio data is ground truth. If holdings are absent or cash-only, use only BUY candidate, WATCH, PASS/AVOID, or cash_reason language; never invent ownership.
- **Confidence:** high
- **Related:** [[ground-truth-portfolio]], [[anti-hallucination]], [[DeciderAgent]]