---
id: DA.code.confirmation_policy
version: code@34ec242ab340
agent: DeciderAgent
title: "CONFIRMATION POLICY"
node_type: code
polarity: gate
polarity_source: override
parent: DA.code
field: null
order: 13
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 20b3a62de63bf246e403aad63cd938fa405d480c7e2bbb246dfb69486ac088d0
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#6"
code_sha: 34ec242ab340
condition: null
fires: true
position: user_prompt_tail
---


CONFIRMATION POLICY (intraday micro-signals only — it never relaxes the regime gate, the extension cap, the re-entry quarantine or the priced-kill requirement): Intraday micro-signals — VWAP, 10-minute and 1-hour trend, and abnormal/relative volume — are FREQUENTLY UNAVAILABLE, above all in the first ~30-45 minutes after the open (no intraday history exists yet) and for the contrarian watchlist. Their absence ('N/A', '0.0x') is EXPECTED and must NEVER by itself block a BUY or force a cash-hold. Confirm with the signals that ARE reliable: multi-day and monthly trend, relative strength vs SPY, position vs the 20-day MA and recent range, the pullback/reversal setup itself, and catalyst. A quality non-extended setup — above all a pullback in an uptrend on a down day (buying the dip) — is BUYABLE on those alone when the regime allows it. PRICED KILL: every BUY reason ends with K:<price>;D:<%>. Form the kill from SUPPLIED numbers — the HIGHER of the watchlist's 20d MA level (or a stated support level) and entry × 0.97 (the 3% kill). The watchlist prints the price, the 20d MA and the 3% kill; the Momentum Recap prints the price. You never need a quoted 'entry reference' beyond that price. If no supplied number puts a kill within 3%, size half; if none within 6%, PASS. The kill is binding on the first breach — no widening, no waiting for the close, no averaging.