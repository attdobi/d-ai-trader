---
id: DA.code.considered_setups
version: code@062f5ef0d69f
agent: DeciderAgent
title: "CONSIDERED SETUPS"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 10
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: fcc3724cdc712d3923f7beaf492b051dba783e9c28b9eb787b8dc2cda17ef0a5
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#3"
code_sha: 062f5ef0d69f
condition: null
fires: true
position: user_prompt_tail
---


CONSIDERED SETUPS (transparency — REQUIRED every cycle, even when you BUY/SELL nothing): Add a top-level "considered" array that audits BOTH sides of this cycle: (1) the SELL/HOLD evaluation of EACH position you currently hold — verdict "hold" or "sell", with the reason you kept or cut it; and (2) the 2-3 best BUY candidates you weighed (your R1..Rk ranked names plus any you seriously rejected). Each element MUST be {"ticker":"SYM", "signals":"day/mo %chg, RS vs SPY, RSI, 20d-MA/range position, volume — concrete numbers", "verdict":"buy"|"sell"|"hold"|"watch"|"reject", "why":"one specific, auditable sentence; for rejects/sells name the exact disqualifier (e.g. 'extended +14% near highs = chase', 'held: fresh entry, thesis intact, normal drawdown', 'sold: thesis broken, support lost')"}. This is the FULL audit of WHY you did what you did (holds/sells + buys) — never leave it empty while you hold positions or have settled funds.