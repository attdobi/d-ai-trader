---
id: DA.code.data_availability
version: code@f42dce4ea4f4
agent: DeciderAgent
title: "DATA-AVAILABILITY RULE"
node_type: code
polarity: caution
polarity_source: override
parent: DA.code
field: null
order: 12
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: a1ddd597fb79f1225143b45ff3bc5357fcbc447661ee92d5a453be5d6d112fb2
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#4"
code_sha: f42dce4ea4f4
condition: null
fires: true
position: user_prompt_tail
---


DATA-AVAILABILITY RULE (do NOT penalize fields that simply were not supplied): VWAP is frequently NOT provided in the momentum data. A missing VWAP must be treated as UNKNOWN — never as a failure or a disqualifier. Confirm entries with the signals you DO have: multi-day trend, relative strength vs SPY, position versus the 20d MA and recent range, supplied catalyst and pullback/reversal geometry. Use intraday trend and volume only when supplied; their absence alone never disqualifies a setup. Only count VWAP against a setup when it IS provided and price is clearly below it. Do NOT stay in cash merely because VWAP (or any single field) was not supplied: a NON-EXTENDED setup remains eligible when the available evidence and all active gates support it. Do not fabricate missing confirmation or force deployment — deploy when a real, non-chase setup clears the signals you actually have.