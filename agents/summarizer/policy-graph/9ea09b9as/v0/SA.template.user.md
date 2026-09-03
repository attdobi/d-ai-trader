---
id: SA.template.user
version: SummarizerAgent.9ea09b9as.v0
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
provenance: prompt_versions#546
sep_before: ""
sep_after: ""
body_sha256: 424185356d70cdaff5016bfacae6dc858a64efeba63342558473148ca57fd076
tags: []
tickers: []
---
Summarize the following financial screenshots and text into **three concise ticker-driven headlines** and a **~200-word insight paragraph**. Focus on short-term catalysts visible in the images.

{feedback_context}

Content:
{content}

FORMAT (STRICT)
Return exactly this JSON structure:
{
  "headlines": ["headline 1", "headline 2", "headline 3"],
  "insights": "single paragraph (~200 words) ending with 'Watchlist: ...'"
}

RULES
- Headlines: 3 total; format `[TICKER] Company — catalyst`; at least 2 must be company-specific.
- Insights: one paragraph (160–220 words) covering regime, sector tilt, key company catalysts (3–5 names), and 1–2 intraday triggers. End with `Watchlist:` (3–8 tickers).
- No invented tickers or macro speculation; every catalyst must reference a concrete cue from the inputs.
- Output **only** the JSON object; no commentary outside it.