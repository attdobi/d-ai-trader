---
id: DA.directives.reminder.loss_cap
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "LOSS CAP"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.reminder
field: strategy_directives
order: 16
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: c6d223f9b1f75eb632b6e7beb456f3418847aacef353026fcf0f4e14a7252407
tags: []
tickers: []
---
1. LOSS CAP — Fully SELL a confirmed holding when its supplied P&L is -0.8% or worse. This active loss cap also applies to a fresh entry and an earnings_event holding; a gap may prevent execution at that exact loss.