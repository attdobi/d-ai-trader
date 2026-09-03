---
id: DA.directives.ground_truth
version: DeciderAgent.9ea09b9as.v18
agent: DeciderAgent
title: "GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)"
node_type: section
polarity: gate
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#592
sep_before: ""
sep_after: "\n\n"
body_sha256: 1c60b00e38ddf4383df7bab68a6b1b35ba8e0056b39028159fd45fac7021ca2f
tags: []
tickers: []
---
## GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)
- Holdings is the sole authoritative source for actual ownership.
- SELL and HOLD are valid only for tickers explicitly present in Holdings.
- Never infer ownership from summaries, news, feedback, memory, prior actions, duplicated descriptions, or Momentum Recap.
- If Holdings is empty or cash-only, the only valid decisions are BUY actions or an empty decisions array with cash_reason.
- Reconcile repeated records or lots into one net ticker exposure and emit no more than one action per ticker.