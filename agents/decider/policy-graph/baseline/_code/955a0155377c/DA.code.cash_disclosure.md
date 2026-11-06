---
id: DA.code.cash_disclosure
version: code@955a0155377c
agent: DeciderAgent
title: "CASH & PROFIT-TAKING DISCLOSURE"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 9
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 7acec5122740ba19ff1435fbfe54c298861d81171da1968c0cd6e42fd5f10f24
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#1"
code_sha: 955a0155377c
condition: null
fires: true
position: user_prompt_tail
---


CASH & PROFIT-TAKING DISCLOSURE: Whenever you output zero BUY actions, add a top-level "cash_reason". Lead with the binding blocker (settled funds ${settled_cash_value}, minimum ticket ${MIN_BUY_AMOUNT}, whole-share feasibility, cooldown, or the best candidate's specific setup/stop failure). Give the regime afterward as sizing context. Confirm that every ≥+3% winner was harvested or name any retained winner with its % gain and fresh catalyst justification. Keep the object compact: {"decisions":[...], "considered":[...], "cash_reason":"..."}.