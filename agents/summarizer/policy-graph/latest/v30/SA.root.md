---
id: SA.root
version: SummarizerAgent.9ea09b9as.v30
agent: SummarizerAgent
title: "Summarizer policy v30"
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
body_sha256: 2bd45961eea9601fd0e5ffb305f2d3e6b8ab5fbd19a178c8887e472adb7bdff8
tags: []
tickers: []
---
Summarizer policy version 30 (config 9ea09b9as, prompt_versions#666, created 2026-10-28 14:45:32 by codex_operator [codex_operator] — Operator audit 2026-10-28: readable approved rules, evidence-grounded learning, and a capped pre-earnings strategy.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 2 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.