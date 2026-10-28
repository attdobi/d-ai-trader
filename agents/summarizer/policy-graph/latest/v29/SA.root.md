---
id: SA.root
version: SummarizerAgent.9ea09b9as.v29
agent: SummarizerAgent
title: "Summarizer policy v29"
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
body_sha256: 175302586347c31b306296fefdf26ec05257459390a902960f68cbab848d7ce8
tags: []
tickers: []
---
Summarizer policy version 29 (config 9ea09b9as, prompt_versions#653, created 2026-10-28 08:29:10 by prompt_lab [human] — v29 Summarizer (auto) · feedback#1263 · success 20.0% · 25 trades · 2026-10-28 15:26 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 2 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.