---
id: SA.root
version: SummarizerAgent.9ea09b9as.v12
agent: SummarizerAgent
title: "Summarizer policy v12"
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
body_sha256: 154415f12696853f784773888b307d9f1373a8b8cba4e245972c686e7e1abf38
tags: []
tickers: []
---
Summarizer policy version 12 (config 9ea09b9as, prompt_versions#587, created 2026-08-13 17:32:42 by system [weekly] — Strategy updated from feedback (ID: 1247)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.