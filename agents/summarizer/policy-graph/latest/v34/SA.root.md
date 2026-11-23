---
id: SA.root
version: SummarizerAgent.9ea09b9as.v34
agent: SummarizerAgent
title: "Summarizer policy v34"
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
body_sha256: 51ae127d81812998037cbbba81731d5a2d348d033fd5a594168f065851bbf2c3
tags: []
tickers: []
---
Summarizer policy version 34 (config 9ea09b9as, prompt_versions#675, created 2026-11-23 07:56:46 by codex_operator [codex_operator] — Identify what fell, when, and which source supports the move or recovery.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 3 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix and code-owned opportunity charter; user prompt = user_prompt_template filled per source plus the sweep's shared operator macro-calendar context, separately labeled from news evidence.