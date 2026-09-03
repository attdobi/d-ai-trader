---
id: SA.memory.log.2026_06_20_synced_positions
version: SummarizerAgent.9ea09b9as.v2
agent: SummarizerAgent
title: "2026-06-20 #synced-positions #evidence-gap"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: SA.memory.log
field: memory
order: 7
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#558
sep_before: ""
sep_after: "\n\n"
body_sha256: cec7ca0cf373e057a5960be36e27a289880ef2935a369cd86594a8825ef1c431
tags: [synced-positions, evidence-gap]
tickers: []
---
## 2026-06-20 #synced-positions #evidence-gap
- **Observation:** Many historical buys were labeled "Schwab synced position," so entry quality cannot be inferred from outcomes.
- **Lesson:** Summaries must not validate inherited inventory. Reconstruct the current thesis from live catalyst + price confirmation, or mark no_catalyst/stale/failing.
- **Confidence:** high
- **Related:** [[DeciderAgent]], [[inventory-triage]], [[ground-truth-portfolio]]