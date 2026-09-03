---
id: DA.code.watchlist_header
version: code@9ee0e6c1cfea
agent: DeciderAgent
title: "# CONTRARIAN WATCHLIST"
node_type: code
polarity: action
polarity_source: override
parent: DA.code
field: null
order: 4
owner: code
status: read-only
compiled: never
locked: true
provenance: contrarian_screener.py:format_contrarian_watchlist
sep_before: ""
sep_after: ""
body_sha256: 50d9eabfa7a6b93e39a1a4653f6b9b01fa6674d951b210bb104b6b1c895377f6
tags: []
tickers: []
source_file: contrarian_screener.py
source_symbol: format_contrarian_watchlist
code_sha: 9ee0e6c1cfea
condition: null
fires: true
position: user_prompt_dynamic
---
# CONTRARIAN WATCHLIST (front-run candidates — pulled back / oversold, NOT extended on either timeframe)
# Screened for the reversal/pullback setups your doctrine targets, capped at 8% above the 20-day MA (the
# swing-timeframe chase metric). For these names a fresh NEWS catalyst is NOT required — the SETUP is the
# thesis (pullback into support within an uptrend, or an oversold turn). Confirm with what is reliable:
# price holding/reclaiming its 20-day MA or recent support, a constructive multi-day/monthly trend, and
# stabilizing relative strength. Do NOT require intraday VWAP/10m/1h — usually absent for pullbacks and
# near the open. PRIORITIZE these for BUY over extended gainers. Each line prints the PRICE, the 20d MA
# level and the 3% kill: your K: is the HIGHER of (20d MA, 3% kill) — write K:<price>;D:<%> from them.
# EXTENDED = 5-8% above the 20d MA: half size and only in RISK-ON. Never buy a name on the QUARANTINE line.