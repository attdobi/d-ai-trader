---
id: DA.code.data_availability
version: code@9ee0e6c1cfea
agent: DeciderAgent
title: "DATA-AVAILABILITY RULE"
node_type: code
polarity: caution
polarity_source: override
parent: DA.code
field: null
order: 11
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 0da67329454d1be3e001201136c3b11b04ff84122a255fb754957d4def5348fd
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#4"
code_sha: 9ee0e6c1cfea
condition: null
fires: true
position: user_prompt_tail
---


DATA-AVAILABILITY RULE (do NOT penalize fields that simply were not supplied): VWAP is frequently NOT provided in the momentum data. A missing VWAP must be treated as UNKNOWN — never as a failure or a disqualifier. Confirm entries with the signals you DO have: day-range / opening-range position, 10-minute AND 1-hour trend, relative strength vs SPY, and volume. Only count VWAP against a setup when it IS provided and price is clearly below it. Do NOT stay in cash merely because VWAP (or any single field) was not supplied: a NON-EXTENDED setup with a fresh catalyst, a positive 10m/1h trend, and adequate volume is buyable even with VWAP absent. Being perpetually in cash is itself a failure mode — deploy when a real, non-chase setup clears the signals you actually have.