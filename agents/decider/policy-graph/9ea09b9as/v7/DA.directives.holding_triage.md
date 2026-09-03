---
id: DA.directives.holding_triage
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "HOLDING TRIAGE"
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
provenance: prompt_versions#568
sep_before: ""
sep_after: "\n\n"
body_sha256: 29322226715c97382dad8880d0f57a8cd0e9d6a90fa2b543f6f824dc564043bd
tags: []
tickers: []
---
HOLDING TRIAGE
- A-quality hold: fresh intraday/≤24h catalyst; above VWAP/opening range; strong 10m trend; relative strength vs SPY/sector; abnormal volume; near highs. HOLD or let breathe 1–3 days.
- B-quality monetize/trim: profitable but stale, extended, crowded, weakening, or lacking fresh catalyst. Prefer SELL full/majority, especially at +3% to +5%.
- C-quality exit: no fresh catalyst, failed catalyst, weak relative strength, below VWAP, weak/flat 10m trend, near lows, or down >1–2% without confirmation. SELL full or at least majority.
- Synced inventory quarantine: classify each inherited holding as winner, small loser, or large loser. Winners without fresh confirmation are harvested; losers without fresh confirmation are cut before they become portfolio wounds.
- Do not produce comforting HOLDs for stale inventory. A HOLD must earn A-quality status or have a clearly defensible current catalyst.
- If the summaries do not provide enough evidence to classify a holding as A-quality, treat it as B/C depending on P&L and tape, not as an automatic hold.