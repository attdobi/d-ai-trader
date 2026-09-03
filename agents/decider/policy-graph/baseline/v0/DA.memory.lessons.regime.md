---
id: DA.memory.lessons.regime
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "#regime — Read the INDEX REGIME line before any BUY."
node_type: lesson
polarity: action
polarity_source: heuristic
parent: DA.memory.lessons
field: memory
order: 4
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: bc9cd349cb0ad95e0c2b295319861c56e2c5c14ea81f0818cedb7d95dd4eb8ff
tags: [regime]
tickers: []
---
- **#regime — Read the INDEX REGIME line before any BUY.** RISK-ON: full rails. MIXED: max 2 new BUYs at half size. RISK-OFF: cash is the default; max 1 half-size BUY in an oversold reversal or a name ≤3% above its 20d MA, harvest at +2%.