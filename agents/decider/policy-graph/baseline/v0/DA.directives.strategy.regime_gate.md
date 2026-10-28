---
id: DA.directives.strategy.regime_gate
version: DeciderAgent.baseline.v0
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
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: 505ff09499c9f539d2a20f2ef8514202c8935140d6fc9ca50e06b4b7f90eab68
tags: []
tickers: []
---
1. REGIME GATE — Read INDEX REGIME before evaluating entries. RISK-ON permits up to 3 new BUYs within full rails. MIXED permits at most 2 at half size, with extension no more than 5%. RISK-OFF permits at most 1 at half size: an oversold reversal or a name no more than 3% above its 20-day MA. In RISK-OFF, harvest at +2%. A missing/unreadable regime is MIXED. Regime changes size and scrutiny, not whether every candidate must be rejected.