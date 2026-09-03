---
id: SA.root
version: SummarizerAgent.9ea09b9as.v16
agent: SummarizerAgent
title: "Summarizer policy v16"
node_type: root
polarity: structure
polarity_source: override
parent: null
field: null
order: 0
owner: generated
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: 8467f556af4acf8a38e6e619114a2012158ae396af14fa3b6d770b6209e95a77
tags: []
tickers: []
---
Summarizer policy version 16 (config 9ea09b9as, prompt_versions#596, created 2026-09-01 18:37:39 by prompt_lab [human] — v16 Summarizer (auto) · feedback#1251 · success 49.1% · 55 trades · 2026-09-01 20:28 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.