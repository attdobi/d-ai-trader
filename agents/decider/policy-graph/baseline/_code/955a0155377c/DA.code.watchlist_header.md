---
id: DA.code.watchlist_header
version: code@955a0155377c
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
body_sha256: 22cd3897e634b7a96f77f9dd9bb5b162a7cda22385ad52d93e986dbed6552111
tags: []
tickers: []
source_file: contrarian_screener.py
source_symbol: format_contrarian_watchlist
code_sha: 955a0155377c
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
# near the open. PRIORITIZE evaluating these over extended gainers. Each line prints PRICE, 20d MA, and a 3% downside reference.
# A 20d MA ABOVE entry is a reclaim/resistance level, not a protective stop. Use it as K only when BELOW entry and supported as relevant support.
# K must be a genuinely evidenced support/invalidation price BELOW entry. Compute positive D = (entry - K) / entry × 100.
# The active D cap still applies. Without a justified below-entry K inside that cap, WATCH/PASS; do not force a BUY.
# The printed 3% reference is not permission or an exception to the active cap. Never invent a tighter stop merely to pass the gate.
# Session recovery can occur while the day is still red. A reclaim and the observed low are evidence to inspect, never an automatic stop or BUY.
# A stale snapshot needs refreshed price and support evidence before entry.
# EXTENDED = 5-8% above the 20d MA: half size and only in RISK-ON. Never buy a name on the QUARANTINE line.