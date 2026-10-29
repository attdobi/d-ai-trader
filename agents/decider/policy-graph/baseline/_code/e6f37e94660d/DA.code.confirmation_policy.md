---
id: DA.code.confirmation_policy
version: code@e6f37e94660d
agent: DeciderAgent
title: "CONFIRMATION POLICY"
node_type: code
polarity: gate
polarity_source: override
parent: DA.code
field: null
order: 14
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: cc0e8ca6517572e032c83bddef86d3528216edd41d5f3c1d5bc9b5fc3c0f6a3e
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#6"
code_sha: e6f37e94660d
condition: null
fires: true
position: user_prompt_tail
---


CONFIRMATION POLICY (intraday micro-signals only — it never relaxes the regime gate, the extension cap, the re-entry quarantine or the priced-kill requirement): Intraday micro-signals — VWAP, 10-minute and 1-hour trend, and abnormal/relative volume — are FREQUENTLY UNAVAILABLE, above all in the first ~30-45 minutes after the open (no intraday history exists yet) and for the contrarian watchlist. Their absence ('N/A', '0.0x') is EXPECTED and must NEVER by itself block a BUY or force a cash-hold. Confirm with the signals that ARE reliable: multi-day and monthly trend, relative strength vs SPY, position vs the 20-day MA and recent range, the pullback/reversal setup itself, and catalyst. A quality non-extended setup — above all a pullback in an uptrend on a down day (buying the dip) — is BUYABLE on those alone when the regime allows it. PRICED KILL: every BUY reason ends with K:<price>;D:<%>. Use a genuinely evidenced support/invalidation price from SUPPLIED numbers BELOW the proposed entry for K. A 20d MA ABOVE entry is a reclaim/resistance level, not a protective stop; use a below-entry MA as K only when supported as relevant support. The watchlist prints the price, the 20d MA and entry × 0.97 as a 3% downside reference; the Momentum Recap prints the price. That reference is not stop authorization or an exception to the active D cap. Compute positive D = (entry - K) / entry × 100. Never invent a tighter stop merely to pass the gate. The active entry gate requires numeric D ≤1.3%; missing, nonpositive or above-cap D means WATCH/PASS, including for earnings-event entries. Without valid below-entry geometry, do not force a BUY. The kill is binding on the first breach — no widening, no waiting for the close, no averaging. The active holding loss cap also requires SELL at P&L -0.8% or worse. Stops cannot guarantee a bound on earnings gap losses.