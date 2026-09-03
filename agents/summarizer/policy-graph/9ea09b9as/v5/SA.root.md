---
id: SA.root
version: SummarizerAgent.9ea09b9as.v5
agent: SummarizerAgent
title: "Summarizer policy v5"
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
body_sha256: b24602a2b1fce5ea279a3ea5048523462960b6eebeef2c2f936e086395c755e4
tags: []
tickers: []
---
Summarizer policy version 5 (config 9ea09b9as, prompt_versions#567, created 2026-06-25 08:45:44 by prompt_lab [human] — v5 Summarizer (auto) · feedback#1237 · success 25.0% · 20 trades · 2026-06-25 15:42 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.