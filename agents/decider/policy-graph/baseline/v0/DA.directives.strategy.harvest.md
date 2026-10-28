---
id: DA.directives.strategy.harvest
version: DeciderAgent.baseline.v0
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
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: ed1f02f468ecaccd6f6ff0816e72191a3b3903b47c34ff1b32a5f7514eb88237
tags: []
tickers: []
---
6. HARVEST — A holding up at least +3%, or +2% in RISK-OFF, is a full SELL by default. Keep it only if RISK-ON and a catalyst no older than 1 trading session remains price-confirmed. Explain the exception; an attractive story alone does not qualify.