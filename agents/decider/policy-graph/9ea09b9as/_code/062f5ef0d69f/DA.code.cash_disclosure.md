---
id: DA.code.cash_disclosure
version: code@062f5ef0d69f
agent: DeciderAgent
title: "CASH & PROFIT-TAKING DISCLOSURE"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 8
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 96b232e7631dcd41dde314f9bc84babc76ae463c5ce1cd3da30a6ce189b4a76b
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#1"
code_sha: 062f5ef0d69f
condition: null
fires: true
position: user_prompt_tail
---


CASH & PROFIT-TAKING DISCLOSURE: If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value} and min buy ${MIN_BUY_AMOUNT}), you must add a top-level "cash_reason" that (a) states why no BUY (caps, cooldown, min-buy unmet, lack of edge, etc.) and (b) confirms that every ≥+3% winner was harvested or explicitly names any retained winner with its % gain and fresh catalyst justification. Keep the object compact: {"decisions":[...], "considered":[...], "cash_reason":"..."}.