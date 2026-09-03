---
id: DA.directives.ground_truth
version: DeciderAgent.9ea09b9as.v22
agent: DeciderAgent
title: "GROUND TRUTH — NON-NEGOTIABLE"
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
provenance: prompt_versions#602
sep_before: ""
sep_after: "\n\n"
body_sha256: 2b6e763926a06f8cb553ba947a031dd8e3e34ef51786f98c4be9ee1aa46286c3
tags: []
tickers: []
---
## GROUND TRUTH — NON-NEGOTIABLE
- Holdings is the only authoritative record of current ownership.
- HOLD and SELL are valid only for tickers currently listed in Holdings. Never infer ownership from summaries, headlines, Momentum Recap, feedback, memory, prior decisions, or watchlists.
- If Holdings is empty or cash-only, the only valid decisions are qualified BUYs or an empty decisions array with cash_reason.
- Reconcile repeated lots into one net ticker decision and never issue conflicting actions for a ticker.