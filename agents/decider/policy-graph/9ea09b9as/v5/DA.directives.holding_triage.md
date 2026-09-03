---
id: DA.directives.holding_triage
version: DeciderAgent.9ea09b9as.v5
agent: DeciderAgent
title: "HOLDING TRIAGE"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#562
sep_before: ""
sep_after: "\n\n"
body_sha256: 0aa2f84e47b74f7e44c1e7443f7a2197b8a3c15da20715fa8b41743ac080787a
tags: []
tickers: []
---
HOLDING TRIAGE
- A-quality hold: fresh ≤24–48h catalyst; above VWAP/opening range; strong 10m trend; relative strength vs SPY/sector; abnormal volume; near highs. HOLD or let breathe 1–3 days.
- B-quality monetize/trim: profitable but stale, extended, crowded, weakening, or lacking fresh catalyst. Prefer SELL full/majority, especially at +3% to +5%.
- C-quality exit: no fresh catalyst, failed catalyst, weak relative strength, below VWAP, weak 10m trend, near lows, or down >2% without confirmation. SELL full or at least majority.
- Synced inventory quarantine: classify each inherited holding as winner, small loser, or large loser. Winners without fresh confirmation are harvested; losers without fresh confirmation are cut before they become portfolio wounds.