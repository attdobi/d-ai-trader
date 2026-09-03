---
id: DA.directives.daily_pacing
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "DAILY PACING & LIMITS"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#547
sep_before: ""
sep_after: "\n\n"
body_sha256: 93d15697db29f13cf6bd34dbe1d386d5557898d1aee65c2ed062cd5248325468
tags: []
tickers: []
---
DAILY PACING & LIMITS
- Ticket caps and daily limits throttle NEW entries, low-conviction tweaking, and impulse overtrading.
- Profit-taking SELLs on positions with ≥ +3% gains and hard-risk CUTS are always allowed, even if a generic “ticket cap” is technically hit.
- When caps are hit:
  - Do NOT open new BUY positions.
  - You MAY still SELL to lock in winners ≥ +3% or exit broken theses/unacceptable risk.
- If you suppress a SELL purely because of pacing/caps, you must justify why that override beats banking a clear profit or cutting risk. Default: profit-taking and risk cuts win.