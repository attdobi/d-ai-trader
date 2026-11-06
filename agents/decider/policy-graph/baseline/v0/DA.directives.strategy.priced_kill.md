---
id: DA.directives.strategy.priced_kill
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "PRICED KILL"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 5
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: 261081747b2a5d3242c18c0832f7fad44f05dc46bfec21adcd42a1067026f404
tags: []
tickers: []
---
3. PRICED KILL — Every BUY needs a numeric entry reference, K:<price> and D:<%> based on supplied numbers. Use the current supplied price as the entry reference. K is a supplied, evidenced support or invalidation level below entry. An above-entry moving average is a reclaim level. The 3% reference cannot authorize a stop; D is the stop's percentage distance below entry. D must be positive and no more than 1.3%. If the required numbers are absent, inconsistent or produce K at/above entry, pass. A calculated record from valid supplied numbers is acceptable; do not require a separately quoted entry price.