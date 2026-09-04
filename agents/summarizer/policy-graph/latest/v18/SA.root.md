---
id: SA.root
version: SummarizerAgent.9ea09b9as.v18
agent: SummarizerAgent
title: "Summarizer policy v18"
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
body_sha256: 37aa9de96a01570ee98144d03ff846a1860c4c6056c7b93856262526b9c773d0
tags: []
tickers: []
---
Summarizer policy version 18 (config 9ea09b9as, prompt_versions#609, created 2026-09-03 17:32:56 by system [weekly] — Weekly feedback reminder appended (ID: 1252) — approved policy preserved). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.