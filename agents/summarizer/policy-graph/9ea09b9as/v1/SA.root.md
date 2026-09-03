---
id: SA.root
version: SummarizerAgent.9ea09b9as.v1
agent: SummarizerAgent
title: "Summarizer policy v1"
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
body_sha256: 5fa836b3ff1a6947d74522dee4a5a391e24230203aa8c7a537a5824b175b8f22
tags: []
tickers: []
---
Summarizer policy version 1 (config 9ea09b9as, prompt_versions#550, created 2026-07-23 17:32:12 by system [weekly] — Strategy updated from feedback (ID: 1242)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.