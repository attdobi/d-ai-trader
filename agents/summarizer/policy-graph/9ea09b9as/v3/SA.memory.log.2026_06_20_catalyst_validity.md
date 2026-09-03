---
id: SA.memory.log.2026_06_20_catalyst_validity
version: SummarizerAgent.9ea09b9as.v3
agent: SummarizerAgent
title: "2026-06-20 #catalyst-validity #timing"
node_type: entry
polarity: evidence
polarity_source: heuristic
parent: SA.memory.log
field: memory
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#561
sep_before: ""
sep_after: "\n\n"
body_sha256: 0e6026dac31ba0b36bd5536b1b57edd0d428a5b267b891dbe10cd3f32168724c
tags: [catalyst-validity, timing]
tickers: [AAL, NVDA, ROKU, USO]
---
## 2026-06-20 #catalyst-validity #timing
- **Observation:** Recent success rate remains weak at ~29–41%, with losses tied to stories that sounded bullish earlier but were not moving price at decision time: [[ROKU]], [[AAL]], [[NVDA]], [[USO]].
- **Lesson:** Add explicit `catalyst_validity` scoring: fresh under 24–48h, above VWAP, strong 10m trend, relative strength vs sector/index, and abnormal volume. Missing evidence means unconfirmed, not bullish.
- **Confidence:** high
- **Related:** [[price-confirmation]], [[relative-strength]], [[failed-catalyst]]