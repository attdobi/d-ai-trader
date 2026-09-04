---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v18
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
provenance: prompt_versions#609
sep_before: ""
sep_after: ""
body_sha256: 156be55624a3475624240cf5305d9a6f48c8f852b24e5194076858a634198d02
tags: []
tickers: []
---
Summarize the following financial screenshots and text into exactly three ticker-driven headlines, three compact catalyst cards, and a 160–220 word insight paragraph whose FIRST sentence is the regime read (risk-on / mixed / risk-off; leaders rising or rolling over) and which ends with 'Watchlist: ...'.

{feedback_context}

Content:
{content}

PROCESS CHECKLIST
1. Screenshots first: index/ETF direction, gainers-versus-losers balance, whether the momentum leaders (AI-infrastructure, semis, quantum/space, high-multiple software) are green or being sold as a group, timestamps, and VWAP/trend/volume/day-position/relative-strength cues.
2. Text second: article publication time vs actual event time, primary source vs recycled, analyst/rumor language, scheduled events (earnings, macro, regulatory — with dates), synchronized coverage across outlets.
3. Classify catalyst_class before status; technical-only and analyst-opinion labels never imply new company information.
4. Flag extension/crowding for any headlined name up ≥8% on the day, at highs on dense coverage, or in synchronized coverage.
5. Portfolio grounding gate: if holdings/portfolio data is present, match it exactly; if absent or cash-only, do not use HOLD/SELL language.
6. Select three tickers by evidence quality and near-term tradability, not fame or headline intensity.
7. actionable_now requires either a fresh catalyst with at least two favorable live-tape cues and no major contradiction, or a technical pullback that is controlled (not extended), in an intact trend, with relative strength that is not weak. Missing data is not confirmation.

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
      "catalyst_class": "hard_corporate_event | regulatory_or_legal_event | analyst_opinion | sector_or_macro | rumor | technical_only | none | unknown",
      "event_time": "event date/time if shown, otherwise not_shown",
      "publication_time": "article date/time if shown, otherwise not_shown",
      "ticker_specificity": "direct | indirect | not_shown",
      "tape": "compact: vwap / trend / day_position / volume / relative_strength from shown cues, else not_shown",
      "extension_flag": "extended_or_crowded | normal | not_shown",
      "event_risk": "scheduled event + date if shown, otherwise none",
      "portfolio_context": "held | not_held | inherited_or_synced | cash_only_or_not_provided | not_shown",
      "tradability": "actionable_now | watch_only | avoid_chasing | avoid_failed_catalyst"
    }
  ],
  "insights": "single paragraph (160–220 words): regime first, sector tilt, crowding/extension flags, the three setups, event risk, ending with 'Watchlist: ...'"
}

RULES
- Headlines: exactly 3 total; format [TICKER] Company — catalyst_status; catalyst; at least 2 must be company-specific.
- A recent publication timestamp is not proof of a fresh event; if the underlying event time is unavailable use event_time: not_shown and do not infer freshness from publication time alone.
- Portfolio context must be exact: held only if the provided portfolio shows ownership; inherited_or_synced only if explicitly shown; not_held if the portfolio is shown and the ticker is absent; cash_only_or_not_provided if no holdings exist or the portfolio is unavailable; otherwise not_shown.
- Do not invent tickers, holdings, technicals, prices, percentages, timestamps, sources, event timing, analyst claims, sector breadth, lot status, or trade history.
- Never treat inherited/synced positions or old headlines as validated buy signals.
- Output only the JSON object; no commentary outside it.