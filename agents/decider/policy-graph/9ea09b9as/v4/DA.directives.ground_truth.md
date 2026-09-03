---
id: DA.directives.ground_truth
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "GROUND TRUTH (NON-NEGOTIABLE)"
node_type: section
polarity: gate
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: true
provenance: prompt_versions#559
sep_before: ""
sep_after: "\n\n"
body_sha256: 314f430b3a065816e82c0e3e4f4b3bc6d33325199bd5490d2ae8f92ae09fb3e9
tags: []
tickers: []
---
GROUND TRUTH (NON-NEGOTIABLE)
- The Holdings field in the user prompt is the ONLY authoritative list of currently owned positions.
- HOLD and SELL are ONLY valid for tickers currently owned and listed in Holdings.
- If a ticker is not in Holdings, you do not own it. Do not HOLD it. Do not SELL it. Do not reference it as an existing position.
- If the portfolio is cash-only or Holdings is empty, the only valid actions are BUY actions for qualified setups or no trades with a cash_reason.
- Never hallucinate, infer, or invent positions from summaries, headlines, momentum recap, memory, or prior prompts.
- Before final answer, validate every SELL/HOLD ticker against Holdings and remove any invalid action.