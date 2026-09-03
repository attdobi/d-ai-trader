---
id: SA.memory.log.2026_09_02_pipeline
version: SummarizerAgent.baseline.v0
agent: SummarizerAgent
title: "2026-09-02 #pipeline #dead-field"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: SA.memory.log
field: memory
order: 5
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n\n"
body_sha256: 9a026b61efba79bd495f2008624a5ac5759396e89b21f82dde06bb44482df51e
tags: [pipeline, dead-field]
tickers: []
---
## 2026-09-02 #pipeline #dead-field
- **Observation:** the 33-field catalyst_validity evidence card evolved through v5–v16 was never consumed — the Decider parses only `headlines` and `insights`; the company-extraction step reads the same two.
- **Lesson:** keep the card compact; spend the tokens on the insights paragraph the Decider actually reads.
- **Confidence:** high (verified in decider_agent.py)