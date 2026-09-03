---
id: DA.directives.loss_containment
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "LOSS CONTAINMENT"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 17
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n\n"
body_sha256: d3ba1736262af86d16de2f0c2240e24c70aca7f85df65ba5420904bff186bc07
tags: []
tickers: []
---
LOSS CONTAINMENT
- Do not allow stale/no-catalyst losers to drift toward -6% to -8%.
- For synced/inherited positions, tighten the exit trigger: if down >1.0–1.5% and below VWAP, weak/flat 10m trend, or negative sector relative strength with no fresh catalyst, SELL full/majority.
- If an owned position is down >2% and lacks a fresh price-confirmed catalyst, SELL full or majority.
- If below VWAP plus weak 10m trend plus weak sector/index confirmation, treat as thesis failure unless an explicit fresh reversal catalyst exists.
- For high-volatility beta, crowded retail names, macro/geopolitical panic trades, and rumor/M&A names, require stronger confirmation to hold; cut faster when confirmation fades.
- Never average down a failed catalyst in a cash account.