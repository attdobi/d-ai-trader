---
id: DA.directives.reminder.kill_breach
version: DeciderAgent.9ea09b9as.v60
agent: DeciderAgent
title: "KILL BREACH"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.reminder
field: strategy_directives
order: 17
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#664
sep_before: ""
sep_after: "\n\n"
body_sha256: 0541d263ade1f964cd1cf943915f19957582c0b6377cd900906d0a818afeb5dc
tags: []
tickers: []
---
2. KILL BREACH — A supplied current price at or below the recorded K triggers SELL; do not widen K or wait for a close. The later reminder's $0.01-below observation does not create a one-cent grace period above this stronger existing stop rule.