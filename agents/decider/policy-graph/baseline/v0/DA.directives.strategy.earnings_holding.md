---
id: DA.directives.strategy.earnings_holding
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "EARNINGS HOLDING"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: 5195bfc0b396bbc3de55fd11c39e08f9dcdc2047d1343eb7cf8e651330f72057
tags: []
tickers: []
---
11. EARNINGS HOLDING — For an ordinary holding with its own earnings release within 2 sessions, SELL before the release; the existing alternative is a trim to half only when RISK-ON and already up at least +3%. An intentionally tagged, runtime-validated earnings_event position may remain through its planned release within the event budget. This exception never overrides a priced stop, the active loss cap or another binding exit.