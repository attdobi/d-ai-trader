---
id: SA.root
version: SummarizerAgent.9ea09b9as.v3
agent: SummarizerAgent
title: "Summarizer policy v3"
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
body_sha256: f61533c40dc361da8917b3c3ef333df0326e93c78401ca4786903fe76712edcb
tags: []
tickers: []
---
Summarizer policy version 3 (config 9ea09b9as, prompt_versions#561, created 2026-06-24 16:18:53 by prompt_lab [human] — v3 Summarizer (auto) · feedback#1235 · success 25.0% · 20 trades · 2026-06-24 22:27 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.