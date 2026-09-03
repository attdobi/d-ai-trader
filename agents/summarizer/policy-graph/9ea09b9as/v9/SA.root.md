---
id: SA.root
version: SummarizerAgent.9ea09b9as.v9
agent: SummarizerAgent
title: "Summarizer policy v9"
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
body_sha256: 404818eb3569b2141b8ecbf4e2bf1f391f0d12876d56dc0f2923e18cfc7c5a04
tags: []
tickers: []
---
Summarizer policy version 9 (config 9ea09b9as, prompt_versions#576, created 2026-07-16 17:31:44 by system [weekly] — Strategy updated from feedback (ID: 1241)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.