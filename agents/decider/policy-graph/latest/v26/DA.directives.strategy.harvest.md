---
id: DA.directives.strategy.harvest
version: DeciderAgent.9ea09b9as.v26
agent: DeciderAgent
title: HARVEST
node_type: rule
polarity: action
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#612
sep_before: ""
sep_after: "\n"
body_sha256: dd3c72ce8c3d802f4fba6a87b8094da89240e8e5d88fef2fc4c516d1e23eb519
tags: []
tickers: []
---
6. HARVEST — ≥ +3% (≥ +2% in RISK-OFF) is a default sell unless a fresh ≤1-session catalyst is still price-confirmed in RISK-ON. With winners capped near +3–5%, the stop distance is the lever, not the harvest.