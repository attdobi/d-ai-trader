---
id: DA.directives.reason_content
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "REASON CONTENT (≤140 chars)"
node_type: section
polarity: action
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 14
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: ""
body_sha256: 0572e91335daf974c6656c92187727b89486b40e5fdef8d65f7d7636a1276444
tags: []
tickers: []
---
REASON CONTENT (≤140 chars)
- Status: “SELL -4.8% …” or “BUY R1: …”
- Catalyst (or “no catalyst”) + timing horizon
- Risk/why now: e.g., “no catalyst; free cash”, “fresh deal; hold 1d”, “stop bleed; rotate”.

If there is any ambiguity between “respect caps” and “bank a clearly profitable winner or cut a broken risk,” you must default to managing P&L and risk (take the profit or cut the loss).