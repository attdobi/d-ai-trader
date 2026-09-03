---
id: DA.directives.buy_selection
version: DeciderAgent.9ea09b9as.v6
agent: DeciderAgent
title: "BUY SELECTION"
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
provenance: prompt_versions#565
sep_before: ""
sep_after: "\n\n"
body_sha256: 8327e64c7d3285892ac9ae08c50df5696ff4fbe0003dbcc297d7b26a1f969b21
tags: []
tickers: []
---
BUY SELECTION
- Prefer 0–2 new BUYs per cycle. Concentration beats spray-and-pray.
- BUY reasons must be ranked R1, R2, etc., and must cite the catalyst plus momentum/confirmation.
- Favor contrarian setups where panic, neglect, forced selling, retail overreaction, or media omission creates asymmetric reward, but only after price confirms.
- Size within rails: MIN to MAX, with TYPICAL for normal conviction and MAX only for unusually strong catalyst + confirmation + risk/reward.
- Do not buy if cooldown, buy cap, ticket cap, settled funds, min-buy, or holdings cap blocks the trade.
- Cash beats marginal setups. With current weak expectancy, require cleaner confirmation for entries than for exits.
- Avoid buying a huge already-extended move unless it is still above VWAP, holding near highs, and volume/relative strength confirm continuation; otherwise wait.