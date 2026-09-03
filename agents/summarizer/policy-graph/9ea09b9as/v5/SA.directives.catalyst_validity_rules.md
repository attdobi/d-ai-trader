---
id: SA.directives.catalyst_validity_rules
version: SummarizerAgent.9ea09b9as.v5
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
provenance: prompt_versions#567
sep_before: ""
sep_after: "\n\n"
body_sha256: 8a2df590b1bf97420e783c76c1400290aa4b325647044f513e115ec3b0e0892b
tags: []
tickers: []
---
CATALYST VALIDITY RULES
- Freshness: Prefer catalysts under 24–48 hours old, and favor fresh intraday catalysts most. Older catalysts require fresh price/volume re-confirmation or should be labeled stale.
- Evidence-quality ranking: Choose tickers with the strongest visible evidence and cleanest short-term catalyst. Do not default to the most popular mega-cap or loudest headline if live tape is missing.
- Current-session confirmation: A catalyst is not actionable unless visible evidence shows above VWAP, strong 10m trend, relative strength vs SPY/QQQ and sector ETF, near intraday highs, abnormal volume, or another explicit live-tape confirmation. If the input does not show this, mark `not_shown` and reduce tradability.
- Minimum actionable gate: `actionable_now` requires a fresh catalyst plus at least two favorable live-tape cues and no major contradictory cue. If confirmation is only partial, use `watch_only`; if extended/fading, use `avoid_chasing`; if contradicted, use `avoid_failed_catalyst`.
- Failed catalyst: If the news sounds bullish but price is below VWAP, near lows, weak/flat/down on the 10m tape, underperforming sector/index, fading from highs, or pinned despite coverage, label it `failing`.
- Fresh confirmed is rare: `fresh_confirmed` requires both a real fresh catalyst and visible current-session confirmation. If any leg is absent, use `fresh_unconfirmed`; if price contradicts, use `failing`.
- Sector confirmation: For single-name catalysts, note whether the sector tape agrees. Chip stories need semiconductor strength; oil stories need energy/crude confirmation; airlines need travel/industrial risk-on confirmation; China ADRs need China/FX/geopolitical tape awareness if visible; retail/consumer stories need discretionary/retail confirmation if visible; banks need financials/rates context if visible; crypto-linked equities need crypto/beta confirmation if visible.
- Avoid stale narrative traps: Post-earnings enthusiasm, AI capex headlines, M&A rumors, geopolitical oil spikes, viral retail chatter, lawsuits, settlements, analyst notes, and prior-month momentum must not be summarized as actionable unless price confirms now.
- Rumor/M&A discipline: Rumors can move fast but fail hard. If M&A/rumor coverage is visible without VWAP/10m/volume confirmation, classify as rumor_MA and watch_only or avoid_chasing.
- Macro/geopolitical panic discipline: Oil, defense, gold, China ADR, and rate-sensitive moves driven by panic headlines require live tape confirmation. If the move has faded, label failing or stale, not bullish.
- Media-manipulation watch: Coordinated coverage without price confirmation is a warning, not a buy thesis. Flag crowded narratives and what the coverage omits.
- Chase-risk discipline: A fresh confirmed name that is visibly fading from highs, pinned, or extended after a large move should not be framed as a clean entry; use `avoid_chasing` unless a fresh intraday re-acceleration trigger is visible.
- Conviction ordering: The Watchlist should rank fresh_confirmed + price/sector-confirmed names first, fresh_unconfirmed names second, and stale/failing/no_catalyst names only if they are important avoids.