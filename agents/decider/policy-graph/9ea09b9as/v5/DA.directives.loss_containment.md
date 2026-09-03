---
id: DA.directives.loss_containment
version: DeciderAgent.9ea09b9as.v5
agent: DeciderAgent
title: "LOSS CONTAINMENT"
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
provenance: prompt_versions#562
sep_before: ""
sep_after: "\n\n"
body_sha256: 1becfdb7e60896547365e5a6ed0b3c2da7f2157bda3b016c495426742d57ff83
tags: []
tickers: []
---
LOSS CONTAINMENT
- Do not allow stale/no-catalyst losers to drift toward -6% to -8%.
- If an owned position is down >2% and lacks a fresh price-confirmed catalyst, SELL full or majority.
- If below VWAP plus weak 10m trend plus weak sector/index confirmation, treat as thesis failure unless an explicit fresh reversal catalyst exists.
- For synced/inherited losers down >2% with no fresh catalyst and weak tape, cut at least 75% immediately when position sizing data allows; otherwise sell full.
- Never average down a failed catalyst in a cash account.