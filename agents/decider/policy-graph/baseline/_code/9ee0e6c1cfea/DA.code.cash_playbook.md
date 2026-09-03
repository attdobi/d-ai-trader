---
id: DA.code.cash_playbook
version: code@9ee0e6c1cfea
agent: DeciderAgent
title: "⏳ CASH ACCOUNT PLAYBOOK (1-5 TRADING DAYS)"
node_type: code
polarity: caution
polarity_source: override
parent: DA.code
field: null
order: 2
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 88a2b08f4d4e47e5e447f35e318b144b18b83babe293d9263215924d6cac0799
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: ask_decision_agent:cash_horizon_block
code_sha: 9ee0e6c1cfea
condition: "not IS_MARGIN_ACCOUNT and '⏳ CASH ACCOUNT PLAYBOOK' not in user_prompt_template"
fires: true
position: user_template_tail
---

⏳ CASH ACCOUNT PLAYBOOK (1-5 TRADING DAYS)
- This is a non-margin cash run; every BUY/SELL should assume a 1-5 session holding window, not a same-day scalp.
- Default to HOLD unless the trade thesis or catalyst broke, price hit your stop, or a clearly superior setup needs the slot. Small mark-to-market noise is not a sell reason.
- Treat the holdings block as the ground-truth P&L (purchase price, current price, gain/loss). Quote those numbers accurately; never describe a loss as a gain.