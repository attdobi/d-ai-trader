---
id: SA.root
version: SummarizerAgent.baseline.v0
agent: SummarizerAgent
title: "Summarizer policy v0"
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
body_sha256: 96e81b23fab403e037ee4825b252fb2681a3944ab68ce992398c6b1db3e119f0
tags: []
tickers: []
---
Summarizer policy version 0 (config baseline, prompt_versions#0, created 2026-01-01 00:00:00 by init_database [seed] — v0 baseline SummarizerAgent — committed with the repository). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 2 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.