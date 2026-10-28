---
id: DA.directives.strategy.extension_cap
version: DeciderAgent.9ea09b9as.v58
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
provenance: prompt_versions#660
sep_before: ""
sep_after: "\n"
body_sha256: 80c33cea030186647828d55493b4bf76ff22d95b7223998072cc015d3529730f
tags: []
tickers: []
---
2. EXTENSION CAP — IF a name is ≤5% above its 20d MA THEN full size. IF 5–8% above THEN half size, RISK-ON only. IF more than 8% above THEN reject it as a chase. Falsified if 20 rejected names above 8% would have averaged better than +1.5% over the next 3 sessions.