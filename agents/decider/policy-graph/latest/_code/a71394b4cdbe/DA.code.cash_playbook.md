---
id: DA.code.cash_playbook
version: code@a71394b4cdbe
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
body_sha256: 489ddb8eac2bb21acdb2eeef32c914496fb0d0f5dca8f69044da622912ce98d6
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: ask_decision_agent:cash_horizon_block
code_sha: a71394b4cdbe
condition: "not IS_MARGIN_ACCOUNT and '⏳ CASH ACCOUNT PLAYBOOK' not in user_prompt_template"
fires: true
position: user_template_tail
---

⏳ CASH ACCOUNT PLAYBOOK (1-5 TRADING DAYS)
- This is a non-margin cash run; every BUY/SELL should assume a 1-5 session holding window, not a same-day scalp.
- Default to HOLD unless the trade thesis or catalyst broke, price hit your stop, or a clearly superior setup needs the slot. Small mark-to-market noise is not a sell reason.
- Use the verified strategy entry basis and current price to assess an open trade when supplied. If only a reported position basis is available, label its unrealized change as such. Broker tax adjustments can affect that basis. Realized strategy P&L requires matched fills and net cash amounts.