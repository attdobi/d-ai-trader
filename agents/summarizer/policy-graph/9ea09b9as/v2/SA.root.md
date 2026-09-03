---
id: SA.root
version: SummarizerAgent.9ea09b9as.v2
agent: SummarizerAgent
title: "Summarizer policy v2"
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
body_sha256: 38014743e8c3a9c333314e1afecdf9cf835b7445ba507b47103f19ee79461001
tags: []
tickers: []
---
Summarizer policy version 2 (config 9ea09b9as, prompt_versions#558, created 2026-06-20 09:04:58 by prompt_lab [human] — v2 Summarizer (auto) · feedback#1234 · success 29.4% · 17 trades · 2026-06-20 16:02 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.