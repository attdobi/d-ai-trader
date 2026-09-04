---
id: DA.code.json_fallback
version: code@34ec242ab340
agent: DeciderAgent
title: "JSON output fallback"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 16
owner: code
status: inactive
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 9312a694186969055d87f19c66b31d9d2d998b95d126bba1e8d7998f3501da39
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:user_prompt_template+="
code_sha: 34ec242ab340
condition: "'JSON' not in user_prompt_template.upper()"
fires: false
position: user_template_tail
---


🚨 CRITICAL TRADING INSTRUCTIONS:

1. FIRST: Review each existing position and decide whether to SELL, providing explicit reasoning
2. SECOND: Consider new BUY opportunities based on news analysis
3. Think in DOLLAR amounts, not share counts - the system will calculate shares

For each EXISTING holding, you MUST provide a sell decision or explicit reasoning why you're keeping it.

🚨 CRITICAL: You must respond ONLY with valid JSON in this exact format:
[
  {{
    "action": "sell" or "buy" or "hold",
    "ticker": "SYMBOL",
    "amount_usd": dollar_amount_number,
    "reason": "detailed explanation including sell analysis for existing positions"
  }}
]

IMPORTANT:
- For SELL: amount_usd = 0 (we sell all shares)
- For BUY: amount_usd = dollars to invest (think $500, $1000, $2000 etc.)
- For HOLD: amount_usd = 0, but provide detailed reasoning why not selling

No explanatory text, no markdown, just pure JSON array.