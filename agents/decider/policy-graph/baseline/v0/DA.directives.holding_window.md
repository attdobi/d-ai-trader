---
id: DA.directives.holding_window
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "HOLDING WINDOW & DATA GUARDRAILS"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 7
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n\n"
body_sha256: fcf024df30d515b34e599733301c6c13af9553d456680c730900b3762ec70511
tags: []
tickers: []
---
HOLDING WINDOW & DATA GUARDRAILS
- In CASH mode, default to letting entries develop across 1–5 sessions.
- SELL early only if the thesis/catalyst invalidates, a stop or risk limit would be hit, or liquidity must be freed for a clearly superior setup.
- Treat the holdings block as factual P&L (purchase price, current price, gain/loss). Quote those figures accurately—never describe a loss as a gain.