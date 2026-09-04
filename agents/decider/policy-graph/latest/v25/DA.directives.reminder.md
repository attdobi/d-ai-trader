---
id: DA.directives.reminder
version: DeciderAgent.9ea09b9as.v25
agent: DeciderAgent
title: "Latest Feedback Reminder (2026-09-03)"
node_type: reminder
polarity: caution
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 11
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#611
sep_before: ""
sep_after: ""
body_sha256: 60eee09a5ac19779e1ea7ade4a404ee243067c10a84e4cb4a5b67de376539469
tags: []
tickers: []
---
## Latest Feedback Reminder (2026-09-03)
- 1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise fall through. Falsified if the next 20 tracked RISK-OFF candidates average >+1.0% over 1-5 days.
- 2. QUARANTINE — If the ticker appears on the QUARANTINE line, PASS; otherwise fall through. Falsified if the next 20 tracked quarantined signals average >+1.0% over 1-5 days.
- 3. PRICED KILL — If the candidate K:/D: line is not numeric with 0<D≤2.4%, PASS; otherwise fall through. Falsified if the next 20 tracked rejects average >+1.0% over 1-5 days.
- 4. KILL BREACH — If a confirmed holding's current price is at/below its recorded K:, SELL; otherwise fall through. Falsified if the next 20 such breaches average >+1.0% over the following 1-5 days.