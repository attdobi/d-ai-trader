---
id: DA.directives.buy_selection
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "BUY SELECTION"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#559
sep_before: ""
sep_after: "\n\n"
body_sha256: dea83df4367bc736d4ef575c7e9f9bd09cb8a12bea5309d1981d28286c5673f2
tags: []
tickers: []
---
BUY SELECTION
- Prefer 0–2 new BUYs per cycle. Concentration beats spray-and-pray.
- BUY reasons must be ranked R1, R2, etc., and must cite the catalyst plus momentum/confirmation.
- Favor contrarian setups where panic, neglect, forced selling, or media omission creates asymmetric reward, but only after price confirms.
- Size within rails: MIN to MAX, with TYPICAL for normal conviction and MAX only for unusually strong catalyst + confirmation + risk/reward.
- Do not buy if cooldown, buy cap, ticket cap, settled funds, or holdings cap blocks the trade.