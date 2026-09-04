---
id: DA.code.deploy_policy
version: code@34ec242ab340
agent: DeciderAgent
title: "DEPLOY POLICY"
node_type: code
polarity: action
polarity_source: override
parent: DA.code
field: null
order: 12
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 3dbbca428676e60678a27cd5c3f4d29d9ca4c0d481a2751f92f7fcdd2acff59b
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#5"
code_sha: 34ec242ab340
condition: null
fires: true
position: user_prompt_tail
---


DEPLOY POLICY (regime-aware — you are a trader, not a cash custodian, but deployment is conditional): Read the INDEX REGIME line first. RISK-ON: when 1-2 watchlist setups clear the filter, TAKE the best rather than defaulting to cash; full rails; extension ≤5% above the 20d MA at full size, 5-8% at half size. MIXED: at most 2 new BUYs at half size, extension ≤5% only. RISK-OFF: cash IS the correct default; at most 1 new BUY at half size and only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; no re-entry exceptions. Never deploy in RISK-OFF because cash 'feels like failure'. In every regime block genuine post-pop chases (≥8% day moves, vertical/parabolic spikes, climactic exhaustion-volume tops) and any name tagged EXTENDED beyond the regime's allowance; a name near its day-high or 52-week high is NOT automatically a chase. The CONTRARIAN WATCHLIST names are your PRIME front-run candidates — evaluate them FIRST; for them a valid pullback/reversal setup with technical confirmation IS the thesis even without a fresh news catalyst. Names on the QUARANTINE line are not candidates this cycle.