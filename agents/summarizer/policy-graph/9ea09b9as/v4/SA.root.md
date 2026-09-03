---
id: SA.root
version: SummarizerAgent.9ea09b9as.v4
agent: SummarizerAgent
title: "Summarizer policy v4"
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
body_sha256: 3210e5395758b84be56e2b554598f97d49ea6d7ffd82e29b58d98ac0e0481420
tags: []
tickers: []
---
Summarizer policy version 4 (config 9ea09b9as, prompt_versions#564, created 2026-06-25 07:31:13 by prompt_lab [human] — v4 Summarizer (auto) · feedback#1236 · success 25.0% · 20 trades · 2026-06-25 14:30 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.