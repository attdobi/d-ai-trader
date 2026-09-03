---
id: SA.directives.catalyst_validity_rules
version: SummarizerAgent.9ea09b9as.v3
agent: SummarizerAgent
title: "CATALYST VALIDITY RULES"
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#561
sep_before: ""
sep_after: "\n\n"
body_sha256: fc788b067cb73438f0a73a5f652b2a03e454c29ca84c071ab12ee42574e1eb3d
tags: []
tickers: []
---
CATALYST VALIDITY RULES
- Freshness: Prefer catalysts under 24–48 hours old. Older catalysts require fresh price/volume re-confirmation or should be labeled stale.
- Current-session confirmation: A catalyst is not actionable unless visible evidence shows above VWAP, strong 10m trend, relative strength vs SPY/QQQ and sector ETF, near intraday highs, or abnormal volume. If the input does not show this, mark `not_shown` and reduce tradability.
- Failed catalyst: If the news sounds bullish but price is below VWAP, near lows, weak on the 10m tape, underperforming sector/index, or pinned despite coverage, label it `failing`.
- Sector confirmation: For single-name catalysts, note whether the sector tape agrees. Chip stories need semiconductor strength; oil stories need energy/crude confirmation; airlines need travel/industrial risk-on confirmation; China ADRs need China/FX/geopolitical tape awareness if visible; retail/consumer stories need discretionary/retail confirmation if visible.
- Avoid stale narrative traps: Post-earnings enthusiasm, AI capex headlines, M&A rumors, geopolitical oil spikes, viral retail chatter, lawsuits, settlements, analyst notes, and prior-month momentum must not be summarized as actionable unless price confirms now.
- Media-manipulation watch: Coordinated coverage without price confirmation is a warning, not a buy thesis. Flag crowded narratives and what the coverage omits.
- Conviction ordering: The Watchlist should rank fresh_confirmed + price/sector-confirmed names first, fresh_unconfirmed names second, and stale/failing/no_catalyst names only if they are important avoids.