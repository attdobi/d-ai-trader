---
id: SA.directives.reminder
version: SummarizerAgent.9ea09b9as.v10
agent: SummarizerAgent
title: "Latest Feedback Reminder: Shift news analysis from story collection to demand verification. For every ticker, provide catalyst_age_hours, catalyst_type, price_vs_VWAP, 10m_trend, 1h_trend, volume_multiple_vs_20d, sector_ETF_direction, closest_peer_confirmation, distance_to_20d, recent_volatility, day_week_month_performance, and explicit missing-data flags. Mark technical-only pullbacks with no fresh tape as decaying theses; these can work for 13h-36h but become stale fast, as seen in SNOW +2.5%, NET +2.1%, SHOP +3.4%,..."
node_type: reminder
polarity: caution
polarity_source: override
parent: SA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#579
sep_before: ""
sep_after: ""
body_sha256: 21fcd4a2b1c91526aa1e4c975446d816f554fae70c0be9b3825f1be32b9a05a1
tags: []
tickers: []
---
Latest Feedback Reminder: Shift news analysis from story collection to demand verification. For every ticker, provide catalyst_age_hours, catalyst_type, price_vs_VWAP, 10m_trend, 1h_trend, volume_multiple_vs_20d, sector_ETF_direction, closest_peer_confirmation, distance_to_20d, recent_volatility, day_week_month_performance, and explicit missing-data flags. Mark technical-only pullbacks with no fresh tape as decaying theses; these can work for 13h-36h but become stale fast, as seen in SNOW +2.5%, NET +2.1%, SHOP +3.4%,...