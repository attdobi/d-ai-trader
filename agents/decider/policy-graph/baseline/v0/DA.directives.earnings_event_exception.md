---
id: DA.directives.earnings_event_exception
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "Earnings-event exception — a separate capped strategy"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 18
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n\n"
body_sha256: b3bd2c1e489081460abd827bc49dc8eff69b1e473e12a0f1b6a6a707d2f90dfd
tags: []
tickers: []
---
## Earnings-event exception — a separate capped strategy
The supplied EARNINGS_EVENT_CONTROLS:v1 block must explicitly enable the exception this cycle. Without it, no earnings-event exception is available. Prefer entries 1–5 trading sessions before the ticker’s own release; today qualifies only with confirmed future release timing. Use only an explicitly tagged earnings_event BUY with a verified supplied ticker/date, intent to hold through the release and accepted gap risk. The hard budget is the smallest of $500, 5% of account value and 25% of the normal per-position cap; at most 1 event position and at most 5% aggregate account exposure. The server's stricter remaining budget is binding. All normal minimum BUY, settled-cash, whole-share, regime, macro, extension, stop, quarantine, correlation and position limits remain. If a whole share/minimum BUY cannot fit, pass; never raise the event cap. A stop does not limit an earnings gap to D: the entire notional can be lost. Do not use an estimated, stale, missing or mismatched earnings date. Do not apply this exception to a normal holding after the fact without a valid intentional event record.