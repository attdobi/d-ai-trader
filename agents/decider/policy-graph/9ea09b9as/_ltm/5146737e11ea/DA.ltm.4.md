---
id: DA.ltm.4
version: ltm@5146737e11ea
agent: DeciderAgent
title: "Do NOT churn your own fresh entries: never SELL a position you opened…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 1
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#4
sep_before: ""
sep_after: ""
body_sha256: 29ee3c90963ff1a020cf1f4c9d3a2fe145475d35a3bf04b660a42753b2987b4e
tags: [churn, provenance, recency]
tickers: []
kind: rule
source: seed
weight: 2.0
ticker: null
row_created_at: 2026-07-01T08:08:12.937451
row_updated_at: 2026-07-01T08:08:12.937451
injected: true
active: true
---
- [rule] Do NOT churn your own fresh entries: never SELL a position you opened within ~2 trading days on ordinary drawdown; respect the 1-5 day swing horizon. 'Cut synced/inherited losers' applies ONLY to positions actually labeled 'Schwab synced position', never your own recent buys.