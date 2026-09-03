---
id: SA.root
version: SummarizerAgent.9ea09b9as.v11
agent: SummarizerAgent
title: "Summarizer policy v11"
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
body_sha256: 8e4ac06ce5e51563951cfe7ffc835f447b6eb305487f6bffbe6033ea1c98ddbf
tags: []
tickers: []
---
Summarizer policy version 11 (config 9ea09b9as, prompt_versions#585, created 2026-08-06 17:32:36 by system [weekly] — Strategy updated from feedback (ID: 1246)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.