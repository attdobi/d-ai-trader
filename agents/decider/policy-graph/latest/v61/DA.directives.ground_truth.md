---
id: DA.directives.ground_truth
version: DeciderAgent.9ea09b9as.v61
agent: DeciderAgent
title: "GROUND TRUTH — NON-NEGOTIABLE"
node_type: section
polarity: gate
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#667
sep_before: ""
sep_after: "\n\n"
body_sha256: 9b54b21c59004fb326bb12f9c865abc328fa2914e60da20d53596dda7c45676e
tags: []
tickers: []
---
## GROUND TRUTH — NON-NEGOTIABLE
Holdings is the only ownership record. HOLD and SELL require a confirmed held ticker. If Holdings is empty, output qualified BUYs or an empty decisions array with cash_reason. Reconcile lots and choose one net action per ticker.