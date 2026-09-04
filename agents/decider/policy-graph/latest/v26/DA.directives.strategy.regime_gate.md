---
id: DA.directives.strategy.regime_gate
version: DeciderAgent.9ea09b9as.v26
agent: DeciderAgent
title: "REGIME GATE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 3
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#612
sep_before: ""
sep_after: "\n"
body_sha256: 959bd842ae3f5da8adca8b271b34f9905f76942f50bd8164657ac9f5597c20b2
tags: []
tickers: []
---
1. REGIME GATE — first, every cycle. RISK-ON = up to 3 new BUYs, full rails. MIXED = ≤2 new BUYs at half size, extension ≤5%. RISK-OFF = cash default, ≤1 half-size BUY (oversold reversal or ≤3% above the 20d MA), harvest at +2%. Falsified if 20 RISK-OFF entries taken under this gate average worse than −1%.