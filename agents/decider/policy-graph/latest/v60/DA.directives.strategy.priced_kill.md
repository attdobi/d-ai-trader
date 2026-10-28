---
id: DA.directives.strategy.priced_kill
version: DeciderAgent.9ea09b9as.v60
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
provenance: prompt_versions#664
sep_before: ""
sep_after: "\n"
body_sha256: a8ee6183d57f45909254efec2fd589b103452cd6c51fafa2790b25a69eadd831
tags: []
tickers: []
---
3. PRICED KILL — Every BUY needs a numeric entry reference, K:<price> and D:<%> based on supplied numbers. Use the current supplied price as the entry reference. K is the higher of the supplied 20-day MA/stated support and entry × 0.97; D is the stop's percentage distance below entry. D must be positive and no more than 1.3%. If the required numbers are absent, inconsistent or produce K at/above entry, pass. A calculated record from valid supplied numbers is acceptable; do not require a separately quoted entry price.