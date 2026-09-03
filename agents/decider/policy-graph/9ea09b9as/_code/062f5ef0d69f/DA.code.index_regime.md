---
id: DA.code.index_regime
version: code@062f5ef0d69f
agent: DeciderAgent
title: "# DEPLOYMENT RULE BY REGIME"
node_type: code
polarity: gate
polarity_source: override
parent: DA.code
field: null
order: 3
owner: code
status: read-only
compiled: never
locked: true
provenance: contrarian_screener.py:format_index_regime
sep_before: ""
sep_after: ""
body_sha256: fc7216a228494fc6cf42141aabcdaf34b8be02cfbd73cc06ae4d2cc02c6cfc18
tags: []
tickers: []
source_file: contrarian_screener.py
source_symbol: format_index_regime
code_sha: 062f5ef0d69f
condition: null
fires: true
position: user_prompt_dynamic
---
# DEPLOYMENT RULE BY REGIME — RISK-ON: full rails, up to 3 new BUYs; extension ≤5% above 20d MA at full size, 5-8% at half size. MIXED: at most 2 new BUYs at half size, extension ≤5% only. RISK-OFF: cash is the correct default; at most 1 new BUY at half size, only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; no re-entry exceptions. The regime never relaxes the priced-kill rule (K:<price>;D:<%>).