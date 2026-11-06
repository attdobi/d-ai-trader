---
id: DA.code.considered_setups
version: code@955a0155377c
agent: DeciderAgent
title: "CONSIDERED SETUPS"
node_type: code
polarity: structure
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
body_sha256: 3e29a6f93ddcda30050021f83db645b3c8f6359c95bd711695b7c8edf1f0fc77
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#3"
code_sha: 955a0155377c
condition: null
fires: true
position: user_prompt_tail
---


CONSIDERED SETUPS (transparency — REQUIRED every cycle, even when you BUY/SELL nothing): Add a top-level "considered" array that audits BOTH sides of this cycle: (1) the SELL/HOLD evaluation of EACH position you currently hold — verdict "hold" or "sell", with the reason you kept or cut it; and (2) each of the first ten supplied contrarian candidates. Evaluate session-reclaim candidates first and give each candidate one compact buy, watch or reject reason. Include any other ranked BUY candidates you weighed. Each element MUST be {"ticker":"SYM", "signals":"day/mo %chg, RS vs SPY, RSI, 20d-MA/range position, volume — concrete numbers", "verdict":"buy"|"sell"|"hold"|"watch"|"reject", "why":"one specific, auditable sentence; for rejects/sells name the exact disqualifier (e.g. 'extended +14% near highs = chase', 'held: fresh entry, thesis intact, normal drawdown', 'sold: thesis broken, support lost')", "cited":["<guideline id>"]}. "cited" is REQUIRED on every "reject" and "watch" element: the 1-2 guideline ids from the GUIDELINE INDEX below that decided the rejection, the deciding gate first, copied exactly as printed — a rejection is a decision too, and each guideline's rejections are counted on the Policy Graph tab. This is the FULL audit of WHY you did what you did (holds/sells + buys) — never leave it empty while you hold positions or have settled funds.