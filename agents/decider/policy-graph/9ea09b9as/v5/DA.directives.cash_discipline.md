---
id: DA.directives.cash_discipline
version: DeciderAgent.9ea09b9as.v5
agent: DeciderAgent
title: "CASH DISCIPLINE"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 15
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#562
sep_before: ""
sep_after: "\n\n"
body_sha256: 57cf003bc32c23f33293365726f4af1e4e43a9d061a87b04f12a6a53277d0743
tags: []
tickers: []
---
CASH DISCIPLINE
- Cash is a valid position when no setup clears the filter.
- If no BUY while settled cash is available, provide cash_reason explaining why no setup qualified and how winners ≥+3% were handled.
- Do not force trades to appear active.