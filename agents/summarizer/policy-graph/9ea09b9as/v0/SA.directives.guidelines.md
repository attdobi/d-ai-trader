---
id: SA.directives.guidelines
version: SummarizerAgent.9ea09b9as.v0
agent: SummarizerAgent
title: GUIDELINES
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#546
sep_before: ""
sep_after: ""
body_sha256: eeedb0972d6851fd13a2ea5bf9317682e8706dbf6e6367eaecc58521c1bc535c
tags: []
tickers: []
---
GUIDELINES
- **Images first**: pull tickers from price tables (Top Gainers/Losers/Most Active), banners, or logos before reading text.
- **Headlines (3 total)**: concise ≤140 chars each; ≥2 must be company+ticker; one macro headline allowed (`[MACRO]`).
- **Insights (~200 words)**: single paragraph, compact sentences. Cover:
  1) Market regime (risk-on/off/mixed) + key macro/sector driver;
  2) Sector tilt (2–3 sectors + why);
  3) 3–5 company drill-downs (ticker — catalyst + image cue);
  4) 1–2 near-term triggers (e.g., “break above HOD”, “fade near VWAP”);
  5) End with `Watchlist:` (3–8 tickers).
- Use semicolons or em-dashes for brevity; skip intro/closing fluff.
- Never invent tickers. Prefer the most liquid class (BRK.B > BRK.A).
- Tie every claim to a visible cue or explicit text reference.
- Stop after the JSON object; no markdown or prose outside it.