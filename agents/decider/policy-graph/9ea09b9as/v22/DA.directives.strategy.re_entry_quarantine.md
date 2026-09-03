---
id: DA.directives.strategy.re_entry_quarantine
version: DeciderAgent.9ea09b9as.v22
agent: DeciderAgent
title: "RE-ENTRY QUARANTINE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#602
sep_before: ""
sep_after: "\n"
body_sha256: b48d4a523fe19e36c01fd1e5190805c827010a2ce1768e0516c4183650e1f6f7
tags: []
tickers: []
---
4. RE-ENTRY QUARANTINE — no BUY within 2 sessions of exiting the same ticker (QUARANTINE line + RECENT ACTIVITY); after a losing exit also require a reclaim of the failed level or a genuinely new catalyst. Falsified if 15 quarantined names would have averaged better than +1% over the next 3 sessions.