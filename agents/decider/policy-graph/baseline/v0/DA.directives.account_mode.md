---
id: DA.directives.account_mode
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "ACCOUNT MODE"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n\n"
body_sha256: 40ed7ea429fccde441385231cbe6c011cd4b55c76e9034da16469e6fee86ed0b
tags: []
tickers: []
---
ACCOUNT MODE
- CASH account:
  - Plan 1–5 trading day swings.
  - Use only Settled Funds for BUYS.
  - Do NOT assume same-day sell proceeds are usable; avoid patterns that rely on unsettled funds (no good-faith violations).
  - Every BUY/SELL assumes a 1–5 session holding window, not a same-day scalp.
- MARGIN account:
  - May use available trading funds and (after sells) proceeds as allowed.
  - May pursue intraday-only clamp downs when rails permit.
  - Still obey the same profit-taking and crowd-fade logic.