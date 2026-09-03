---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v4
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
provenance: prompt_versions#564
sep_before: ""
sep_after: ""
body_sha256: 3222bccd1fea764ec196ff374feda0d79b887a8916b9c2aeaac64a4da5aa1076
tags: []
tickers: []
---
Summarize the following financial screenshots and text into exactly three ticker-driven headlines, a catalyst-validity table, and a 160–220 word insight paragraph. Focus on short-term catalysts visible in the images and text, but grade whether each catalyst is still being rewarded by current-session price action.

{feedback_context}

Content:
{content}

PROCESS CHECKLIST
1. Screenshot evidence first: visible tickers, charts, VWAP, 10m trend, volume, sector/index cues, timestamps, intraday high/low proximity.
2. Text evidence second: headline age, source, catalyst specificity, rumor/M&A language, macro/geopolitical panic framing, repeated/crowded coverage.
3. Portfolio grounding gate: if holdings/portfolio data is present, match it exactly. If absent or cash-only, do not imply HOLD/SELL/existing-position language.
4. For each selected ticker, decide catalyst_freshness first: fresh_intraday, fresh_24_48h, stale_prior_session, rumor_MA, macro_geopolitical_panic, recycled_media, inherited_inventory, no_catalyst, or not_shown.
5. Then decide status: fresh_confirmed, fresh_unconfirmed, stale, failing, or no_catalyst.
6. Require visible price/volume/relative-strength evidence for actionable_now. If confirmation is missing, use not_shown and reduce tradability.
7. Prefer avoid/watch labels over false conviction when confirmation is missing or contradictory.

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
      "evidence": "concrete cue from image/text; include inherited/synced/stale cue if shown",
      "price_confirmation": "above_vwap | below_vwap | strong_10m | weak_10m | near_highs | near_lows | abnormal_volume | fading_from_highs | pinned | not_shown",
      "sector_confirmation": "confirmed | conflicting | not_shown",
      "portfolio_context": "held | not_held | inherited_or_synced | cash_only_or_not_provided | not_shown",
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
  - `failing`: bullish/bearish story is contradicted by visible price action, weak/flat 10m trend, below VWAP, near lows, fading from highs, sector conflict, pinned tape, or failed follow-through.
  - `no_catalyst`: ticker appears without a concrete tradable reason.
- Price confirmation must be based only on visible cues: above/below VWAP, strong/weak 10m trend, near intraday highs/lows, relative strength, abnormal volume, fading from highs, or pinned tape. If absent, use `not_shown`.
- Sector confirmation must be based only on visible or explicit cues. If not visible, use `not_shown`.
- Portfolio context must be exact: `held` only if the provided portfolio shows ownership; `inherited_or_synced` only if explicitly shown/stated; `not_held` if portfolio is shown and ticker is absent; `cash_only_or_not_provided` if no holdings exist or portfolio is unavailable; otherwise `not_shown`.
- Insights: one paragraph only, 160–220 words, covering regime, sector tilt, the 3 selected catalysts, failed/stale/crowded narrative risks, inherited/synced inventory risk if present, and 1–2 intraday triggers. End with `Watchlist:` followed by 3–8 tickers ordered by conviction.
- No invented tickers, holdings, technicals, prices, percentages, timestamps, analyst claims, macro speculation, or sector breadth without a concrete input cue.
- Never treat inherited/synced positions or old headlines as validated buy signals.
- Output only the JSON object; no commentary outside it.