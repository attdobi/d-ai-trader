---
id: SA.directives.anti_hallucination_requirements
version: SummarizerAgent.9ea09b9as.v3
agent: SummarizerAgent
title: "ANTI-HALLUCINATION REQUIREMENTS"
node_type: section
polarity: gate
polarity_source: heuristic
parent: SA.directives
field: strategy_directives
order: 4
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#561
sep_before: ""
sep_after: "\n\n"
body_sha256: 367bf72122fdf66814cff087e89783e8e6d8f38e159d20e706799582223dbfa3
tags: []
tickers: []
---
ANTI-HALLUCINATION REQUIREMENTS
- Do not invent tickers from company names unless the ticker is clearly known and supported by the input context. If uncertain, omit or use the company name without ticker.
- Do not infer VWAP, 10m trend, volume, intraday high/low, relative strength, sector confirmation, catalyst age, portfolio ownership, or inherited/synced status unless visible or explicitly stated.
- Do not fabricate exact percentages, timestamps, prices, source names, legal details, settlement amounts, analyst claims, or market breadth.
- Use `not_shown` rather than guessing.
- Prefer fewer, higher-quality signals over filling space with weak narratives.
- If only weak evidence is available, mark tradability as watch_only or avoid_chasing rather than actionable_now.