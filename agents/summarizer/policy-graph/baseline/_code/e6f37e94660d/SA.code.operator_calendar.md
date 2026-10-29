---
id: SA.code.operator_calendar
version: code@e6f37e94660d
agent: SummarizerAgent
title: "OPERATOR MACRO CALENDAR"
node_type: code
polarity: structure
polarity_source: override
parent: SA.code
field: null
order: 3
owner: code
status: read-only
compiled: never
locked: true
provenance: summary_event_context.py:render_summary_calendar
sep_before: ""
sep_after: ""
body_sha256: 68ba741ae4169bcb05afcd33981a901bd0734c43dae19ee3fedcd6a1dd58c0b4
tags: []
tickers: []
source_file: summary_event_context.py
source_symbol: render_summary_calendar
code_sha: e6f37e94660d
condition: null
fires: true
position: user_prompt_dynamic
---
# OPERATOR MACRO CALENDAR — code context, not news evidence
Use this as operator_calendar context in the existing EVENT CALENDAR sentence; distinguish it from facts observed in the news source. A supplied date does not mean an article mentioned it or that a company claim is verified.
This block supplies no index regime, portfolio risk score, ownership, company earnings dates or trade-sizing allowance. Unprovided company/event details remain not_shown; the Decider enriches and applies the current approved controls later.
A macro-window flag alone neither rejects every opportunity nor orders a trade. Preserve the existing headline/card JSON contract and insights word budget; do not add fields for this block.