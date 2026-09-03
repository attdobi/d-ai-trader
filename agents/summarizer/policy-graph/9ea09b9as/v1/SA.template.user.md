---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v1
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
provenance: prompt_versions#550
sep_before: ""
sep_after: ""
body_sha256: c36578f4abf447959f8f88d63d4e0ed288608cd17f8c58cccf8c0340309bfdfe
tags: []
tickers: []
---
Summarize the following financial screenshots and text into exactly three ticker-driven headlines, a catalyst-validity table, and a 160–220 word insight paragraph. Focus on short-term catalysts visible in the images and text, but grade whether each catalyst is still being rewarded by current-session price action.

{feedback_context}

Content:
{content}

PROCESS CHECKLIST
1. Screenshot evidence first: visible tickers, charts, VWAP, 10m trend, volume, sector/index cues, timestamps, intraday high/low proximity, and relative strength.
2. Text evidence second: headline age, source, catalyst specificity, rumor/M&A language, macro/geopolitical panic framing, repeated/crowded coverage, and whether the story is recycled.
3. Portfolio grounding gate: if holdings/portfolio data is present, match it exactly. If absent or cash-only, do not imply HOLD/SELL/existing-position language.
4. Select the three tickers by evidence quality and near-term tradability, not fame or headline intensity.
5. For each selected ticker, decide catalyst_freshness first: fresh_intraday, fresh_24_48h, stale_prior_session, rumor_MA, macro_geopolitical_panic, recycled_media, inherited_inventory, no_catalyst, or not_shown.
6. Record catalyst_age, VWAP, 10m trend, day position, volume confirmation, relative strength, sector confirmation, portfolio context, and media risk using only visible/explicit cues.
7. Then decide status: fresh_confirmed, fresh_unconfirmed, stale, failing, or no_catalyst.
8. Require visible price/volume/relative-strength evidence for actionable_now. If confirmation is missing, mixed, or contradictory, use not_shown/mixed/conflicting and reduce tradability.
9. Prefer avoid/watch labels over false conviction when confirmation is missing or contradictory.

FORMAT (STRICT)
Return exactly one valid JSON object with this structure:
{
  "headlines": ["headline 1", "headline 2", "headline 3"],
  "catalyst_validity": [
    {
      "ticker": "TICKER",
      "company": "Company",
      "status": "fresh_confirmed | fresh_unconfirmed | stale | failing | no_catalyst",
      "catalyst_freshness": "fresh_intraday | fresh_24_48h | stale_prior_session | rumor_MA | macro_geopolitical_panic | recycled_media | inherited_inventory | no_catalyst | not_shown",
      "catalyst_age": "intraday | 24_48h | older_than_48h | not_shown",
      "evidence": "concrete cue from image/text; include inherited/synced/stale cue if shown",
      "vwap": "above | below | mixed | not_shown",
      "trend_10m": "strong_up | weak_up | flat | down | mixed | not_shown",
      "day_position": "near_highs | midrange | near_lows | fading_from_highs | pinned | not_shown",
      "volume_confirmation": "abnormal | normal | weak | not_shown",
      "relative_strength": "outperforming_index_sector | in_line | underperforming_index_sector | conflicting | not_shown",
      "sector_confirmation": "confirmed | conflicting | not_shown",
      "portfolio_context": "held | not_held | inherited_or_synced | cash_only_or_not_provided | not_shown",
      "media_risk": "low | crowded | promotional | rumor_driven | panic_driven | stale_recycled | not_shown",
      "tradability": "actionable_now | watch_only | avoid_chasing | avoid_failed_catalyst"
    }
  ],
  "insights": "single paragraph (160-220 words) ending with 'Watchlist: ...'"
}

RULES
- Headlines: exactly 3 total; format `[TICKER] Company — catalyst_status; catalyst`; at least 2 must be company-specific.
- Catalyst status definitions:
  - `fresh_confirmed`: under 24–48h old and supported by visible current-session price/volume/relative-strength confirmation.
  - `fresh_unconfirmed`: under 24–48h old but VWAP/10m/volume/sector/relative-strength confirmation is missing, mixed, or not visible.
  - `stale`: older story, prior momentum, widely circulated coverage, inherited/synced inventory without a fresh trigger, or catalyst whose initial move has already faded.
  - `failing`: bullish/bearish story is contradicted by visible price action, weak/flat/down 10m trend, below VWAP, near lows, fading from highs, sector conflict, pinned tape, or failed follow-through.
  - `no_catalyst`: ticker appears without a concrete tradable reason.
- `actionable_now` is allowed only when the catalyst is fresh and at least two live-tape cues are favorable, with no major contradiction visible. Otherwise use watch_only, avoid_chasing, or avoid_failed_catalyst.
- Price confirmation must be based only on visible cues: VWAP, 10m trend, intraday high/low proximity, relative strength, abnormal volume, fading from highs, or pinned tape. If absent, use `not_shown`.
- Sector confirmation must be based only on visible or explicit cues. If not visible, use `not_shown`.
- Portfolio context must be exact: `held` only if the provided portfolio shows ownership; `inherited_or_synced` only if explicitly shown/stated; `not_held` if portfolio is shown and ticker is absent; `cash_only_or_not_provided` if no holdings exist or portfolio is unavailable; otherwise `not_shown`.
- Insights: one paragraph only, 160–220 words, covering regime, sector tilt, the 3 selected catalysts, failed/stale/crowded narrative risks, inherited/synced inventory risk if present, and 1–2 intraday triggers. End with `Watchlist:` followed by 3–8 tickers ordered by conviction.
- No invented tickers, holdings, technicals, prices, percentages, timestamps, analyst claims, macro speculation, or sector breadth without a concrete input cue.
- Never treat inherited/synced positions or old headlines as validated buy signals.
- Output only the JSON object; no commentary outside it.