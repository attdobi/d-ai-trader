---
id: SA.root
version: SummarizerAgent.9ea09b9as.v8
agent: SummarizerAgent
title: "Summarizer policy v8"
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
body_sha256: 23fa4b6fbce796b889a255ddda3d3447fcb5372042e8f9086493c879b9c48549
tags: []
tickers: []
---
Summarizer policy version 8 (config 9ea09b9as, prompt_versions#574, created 2026-07-09 17:31:05 by system [weekly] — Strategy updated from feedback (ID: 1240)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.