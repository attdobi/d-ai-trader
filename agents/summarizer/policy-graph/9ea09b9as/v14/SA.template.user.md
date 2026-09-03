---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v14
agent: SummarizerAgent
title: "User prompt template"
node_type: template
polarity: structure
polarity_source: override
parent: SA.root
field: user_prompt_template
order: 0
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#591
sep_before: ""
sep_after: ""
body_sha256: f62f2bea1c4dd50e693815c6f2bcbb8cd531ca2516ccd55c052aeb600db497a4
tags: []
tickers: []
---
Summarize the following financial screenshots and text into exactly three ticker-driven headlines, a catalyst-validity evidence card, and a 160–220 word insight paragraph. Focus on short-term catalysts and explicitly shown technical-pullback structures, then grade whether current-session price action supports them.

{feedback_context}

Content:
{content}

PROCESS CHECKLIST
1. Screenshot evidence first: visible tickers, charts, VWAP, 10m trend, volume, sector/index cues, timestamps, intraday high/low proximity, relative strength, and—if supplied—20-day trend and RS20.
2. Text evidence second: publication age, primary source, catalyst specificity and novelty, rumor/M&A language, macro/geopolitical panic framing, repeated/crowded coverage, and whether the story is recycled.
3. Portfolio grounding gate: if holdings/portfolio data is present, match it exactly. If absent or cash-only, do not imply HOLD, SELL, or existing-position language.
4. Select the three tickers by evidence quality and near-term tradability, not fame or headline intensity.
5. Classify setup_type first: fresh_catalyst, technical_pullback, mixed, or unknown. A no-news technical pullback is not automatically bearish.
6. For each selected ticker, decide catalyst_freshness first: fresh_intraday, fresh_24_48h, stale_prior_session, rumor_MA, macro_geopolitical_panic, recycled_media, inherited_inventory, no_catalyst, or not_shown.
7. Record catalyst age, publication time, primary source, novelty, VWAP, 10m trend, day position, volume confirmation, relative strength, sector confirmation, 20-day trend, RS20, pullback state, reversal confirmation, portfolio context, and media risk using only visible or explicit cues.
8. Then decide status: fresh_confirmed, fresh_unconfirmed, stale, failing, or no_catalyst.
9. `actionable_now` requires either: a fresh catalyst with at least two favorable live-tape cues and no major contradiction; or a technical pullback with explicitly shown positive RS20, intact/above 20-day trend, controlled pullback, non-down/non-failing 10m reversal, and non-weak relative strength or sector confirmation.
10. If confirmation is missing, mixed, or contradictory, use not_shown, mixed, or conflicting and reduce tradability. Prefer watch/avoid labels over false conviction.

FORMAT (STRICT)
Return exactly one valid JSON object with this structure:
{
  "headlines": ["headline 1", "headline 2", "headline 3"],
  "catalyst_validity": [
    {
      "ticker": "TICKER",
      "company": "Company",
      "setup_type": "fresh_catalyst | technical_pullback | mixed | unknown",
      "status": "fresh_confirmed | fresh_unconfirmed | stale | failing | no_catalyst",
      "catalyst_freshness": "fresh_intraday | fresh_24_48h | stale_prior_session | rumor_MA | macro_geopolitical_panic | recycled_media | inherited_inventory | no_catalyst | not_shown",
      "catalyst_age": "intraday | 24_48h | older_than_48h | not_shown",
      "publication_time": "exact date/time if shown, otherwise not_shown",
      "primary_source": "direct_company_regulatory_filing | reputable_media | social_or_aggregator | not_shown",
      "novelty": "new | incremental_or_recycled | not_shown",
      "evidence": "concrete cue from image/text",
      "vwap": "above | below | mixed | not_shown",
      "trend_10m": "strong_up | weak_up | flat | down | mixed | not_shown",
      "day_position": "near_highs | midrange | near_lows | fading_from_highs | pinned | not_shown",
      "volume_confirmation": "abnormal | normal | weak | not_shown",
      "relative_strength": "outperforming_index_sector | in_line | underperforming_index_sector | conflicting | not_shown",
      "sector_confirmation": "confirmed | conflicting | not_shown",
      "trend_20d": "above_and_intact | below_or_broken | mixed | not_shown",
      "rs_20d": "positive | nonpositive | not_shown",
      "pullback_state": "controlled | extended_or_chasing | not_shown",
      "reversal_confirmation": "confirmed | absent_or_mixed | not_shown",
      "portfolio_context": "held | not_held | inherited_or_synced | cash_only_or_not_provided | not_shown",
      "media_risk": "low | crowded | promotional | rumor_driven | panic_driven | stale_recycled | not_shown",
      "tradability": "actionable_now | watch_only | avoid_chasing | avoid_failed_catalyst"
    }
  ],
  "insights": "single paragraph (160-220 words) ending with 'Watchlist: ...'"
}

RULES
- Headlines: exactly 3 total; format `[TICKER] Company — catalyst_status; catalyst`; at least 2 must be company-specific.
- `fresh_confirmed` requires a fresh catalyst plus visible current-session confirmation. `fresh_unconfirmed` means a fresh catalyst lacks complete confirmation. `stale` covers older, recycled, inherited, or faded catalysts. `failing` means visible tape contradicts the story. `no_catalyst` means no fresh event/news catalyst is shown.
- A `technical_pullback` can be actionable without fresh news only when every technical-pullback requirement in the checklist is explicitly evidenced. Missing data is not confirmation.
- Portfolio context must be exact: `held` only if the provided portfolio shows ownership; `inherited_or_synced` only if explicitly shown/stated; `not_held` if portfolio is shown and ticker is absent; `cash_only_or_not_provided` if no holdings exist or portfolio is unavailable; otherwise `not_shown`.
- Do not invent tickers, holdings, technicals, prices, percentages, timestamps, sources, analyst claims, macro speculation, sector breadth, lot status, or trade history.
- Never treat inherited/synced positions or old headlines as validated buy signals.
- Output only the JSON object; no commentary outside it.