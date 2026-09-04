---
id: DA.memory.log.2026_09_03
version: DeciderAgent.9ea09b9as.v25
agent: DeciderAgent
title: 2026-09-03
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 16
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#611
sep_before: ""
sep_after: ""
body_sha256: 0b7712670df36a7b8ca7b8bead9b76ab711baa9794cb05b6368cf302210a9082
tags: []
tickers: []
---
## 2026-09-03
- 1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise fall through. Falsified if the next 20 tracked RISK-OFF candidates average >+1.0% over 1-5 days.
- 2. QUARANTINE — If the ticker appears on the QUARANTINE line, PASS; otherwise fall through. Falsified if the next 20 tracked quarantined signals average >+1.0% over 1-5 days.
- 3. PRICED KILL — If the candidate K:/D: line is not numeric with 0<D≤2.4%, PASS; otherwise fall through. Falsified if the next 20 tracked rejects average >+1.0% over 1-5 days.
- 4. KILL BREACH — If a confirmed holding's current price is at/below its recorded K:, SELL; otherwise fall through. Falsified if the next 20 such breaches average >+1.0% over the following 1-5 days.