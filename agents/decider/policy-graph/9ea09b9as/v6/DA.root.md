---
id: DA.root
version: DeciderAgent.9ea09b9as.v6
agent: DeciderAgent
title: "Decider policy v6"
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
body_sha256: dc519a04133aa7418877b9b2dad90ef7a49739d6cda60b5fb249dcfa14fdf3a0
tags: []
tickers: []
---
Decider policy version 6 (config 9ea09b9as, prompt_versions#565, created 2026-06-25 07:32:00 by prompt_lab [human] — v6 Decider (auto) · feedback#1236 · success 25.0% · 20 trades · 2026-06-25 14:30 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 15 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).