---
id: DA.directives.strategy.extension_cap
version: DeciderAgent.9ea09b9as.v60
agent: DeciderAgent
title: "EXTENSION CAP"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 4
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#664
sep_before: ""
sep_after: "\n"
body_sha256: edc243663683d6c49b8e4f0d98c55304376b5ba6fba16549923015ce3b4ba8b1
tags: []
tickers: []
---
2. EXTENSION CAP — At no more than 5% above the 20-day MA, an entry can use the size otherwise allowed by regime and account rules. Above 5% through 8%, only a half-size RISK-ON entry is eligible. Above 8%, reject the chase. A red day does not remove an extended swing entry's risk.