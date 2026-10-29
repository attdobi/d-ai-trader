---
id: DA.code.index_regime
version: code@e6f37e94660d
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
body_sha256: ac7b123715399dcbe216a1f7dbc60698a4e5f18a7bdeae72b3dcac42db962669
tags: []
tickers: []
source_file: contrarian_screener.py
source_symbol: format_index_regime
code_sha: e6f37e94660d
condition: null
fires: true
position: user_prompt_dynamic
---
# DEPLOYMENT RULE BY REGIME — RISK-ON: full rails, up to 3 new BUYs; extension ≤5% above 20d MA at full size, 5-8% at half size. MIXED: at most 2 new BUYs at half size, extension ≤5% only. RISK-OFF: evaluate selective opportunities; at most 1 new BUY at half size, only an oversold reversal or a name ≤3% above its 20d MA; harvest at +2%; no re-entry exceptions. Hold cash when independent candidate gates fail; never force a BUY. The regime never relaxes the priced-kill rule (K:<price>;D:<%>).