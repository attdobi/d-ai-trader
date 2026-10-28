---
id: DA.directives.strategy.candidates
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: CANDIDATES
node_type: rule
polarity: mixed
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 10
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: a62da5d606f2ab877d48b3dacdfcf57fd59da6c365e9a61921023466d33fc64f
tags: []
tickers: []
---
8. CANDIDATES — IF fewer than 2 candidates were weighed this cycle THEN pass. Otherwise rank accepted BUYs R1..Rk from supplied evidence only. Falsified if 20 one-candidate cycles average better than 20 cycles that weighed 2–3.