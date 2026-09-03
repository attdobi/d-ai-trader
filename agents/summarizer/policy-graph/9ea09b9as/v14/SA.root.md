---
id: SA.root
version: SummarizerAgent.9ea09b9as.v14
agent: SummarizerAgent
title: "Summarizer policy v14"
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
body_sha256: e8d800a4a27cac96086dff76cdc6288fe39e6a6259c44ca9e072de51fec1110a
tags: []
tickers: []
---
Summarizer policy version 14 (config 9ea09b9as, prompt_versions#591, created 2026-08-21 16:08:04 by prompt_lab [human] — v14 Summarizer (auto) · feedback#1249 · success 62.2% · 45 trades · 2026-08-21 22:48 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.