---
id: DA.memory.log.2026_07_01_intc
version: DeciderAgent.9ea09b9as.v8
agent: DeciderAgent
title: "2026-07-01 #INTC #LRCX #churn #provenance"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 7
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#571
sep_before: ""
sep_after: ""
body_sha256: 7dc49df29e31ebde8adea53a366ac7375acf76f64a64196113cea85120261e2b
tags: [intc, lrcx, churn, provenance]
tickers: [INTC, LRCX]
---
## 2026-07-01 #INTC #LRCX #churn #provenance
- **Setup:** Bought INTC/LRCX as R1/R2 pullback dips (down ~5-7% on the day inside a +20%+ month uptrend). ~35 min later SOLD both as "synced/inherited losers" at a small loss.
- **Root cause:** the Schwab position sync overwrote each holding's buy reason with "Schwab synced position" and reset purchase_timestamp, so the decider forgot they were its OWN fresh entries and cut them on normal entry drawdown — incoherent churn (bought the dip, sold because it was a dip).
- **Adjustment:** provenance is now preserved across syncs (reason + purchase time), and Holdings shows position age. NEVER cut your own recent entry (real buy reason, held < ~2 trading days) on ordinary drawdown — a dip you bought being down is expected entry noise, not a thesis break. "Cut synced losers" applies ONLY to genuinely inherited positions. **Related:** [[front-run-not-chase]]