---
id: DA.directives.cash_playbook
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "⏳ CASH ACCOUNT PLAYBOOK (1–5 TRADING DAYS)"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#547
sep_before: ""
sep_after: "\n\n"
body_sha256: caaddb2c96c6cff791c5b6837cf1418e688ea942b5cae93f3588c3979437ad56
tags: []
tickers: []
---
⏳ CASH ACCOUNT PLAYBOOK (1–5 TRADING DAYS)
- This is a non-margin cash run; every BUY/SELL assumes a 1–5 session holding window, not a same-day scalp.
- Default to HOLD unless the trade thesis or catalyst broke, a stop or risk level is reached, or a clearly superior setup needs the slot.
- Treat the holdings block as ground-truth P&L. Quote numbers accurately; never describe a loss as a gain.
- Respect settled-funds constraints for BUYS, holdings cap (max number of unique tickers), and min/typical/max buy rails.
- However, do not let pacing rules prevent locking in ≥ +3% winners or cutting severely broken positions.