---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v2
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
provenance: prompt_versions#558
sep_before: ""
sep_after: ""
body_sha256: 5cf99885456f815b02527561f51ebdee97a2bb4b5052fe7eb182cb7eae0eefc5
tags: []
tickers: []
---
Summarize the following financial screenshots and text into three concise ticker-driven headlines, a catalyst-validity table, and a ~200-word insight paragraph. Focus on short-term catalysts visible in the images and text.

{feedback_context}

Content:
{content}

FORMAT (STRICT)
Return exactly one valid JSON object with this structure:
{
  "headlines": ["headline 1", "headline 2", "headline 3"],
  "catalyst_validity": [
    {
      "ticker": "TICKER",
      "company": "Company",
      "status": "fresh_confirmed | fresh_unconfirmed | stale | failing | no_catalyst",
      "evidence": "concrete cue from image/text",
      "price_confirmation": "above_vwap | below_vwap | strong_10m | weak_10m | near_highs | near_lows | abnormal_volume | not_shown",
      "sector_confirmation": "confirmed | conflicting | not_shown",
      "tradability": "actionable_now | watch_only | avoid_chasing | avoid_failed_catalyst"
    }
  ],
  "insights": "single paragraph (160-220 words) ending with 'Watchlist: ...'"
}

RULES
- Headlines: exactly 3 total; format `[TICKER] Company — catalyst_status; catalyst`; at least 2 must be company-specific.
- Catalyst status definitions:
  - `fresh_confirmed`: under 24–48h old and supported by visible price/volume confirmation.
  - `fresh_unconfirmed`: under 24–48h old but price/sector confirmation is missing or not visible.
  - `stale`: older story, already widely circulated, or prior momentum without a new trigger.
  - `failing`: bullish/bearish story is contradicted by visible price action, weak 10m trend, below VWAP, near lows, sector conflict, or failed follow-through.
  - `no_catalyst`: ticker appears without a concrete tradable reason.
- Price confirmation must be based only on visible cues: above/below VWAP, strong/weak 10m trend, near intraday highs/lows, relative strength, or abnormal volume. If absent, use `not_shown`.
- Insights: one paragraph only, 160–220 words, covering regime, sector tilt, key company catalysts, failed/stale narrative risks, and 1–2 intraday triggers. End with `Watchlist:` followed by 3–8 tickers ordered by conviction.
- No invented tickers, no invented holdings, no invented technicals, no macro speculation without a concrete input cue.
- Never treat inherited/synced positions or old headlines as validated buy signals.
- Output only the JSON object; no commentary outside it.