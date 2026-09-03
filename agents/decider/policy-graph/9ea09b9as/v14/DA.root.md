---
id: DA.root
version: DeciderAgent.9ea09b9as.v14
agent: DeciderAgent
title: "Decider policy v14"
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
body_sha256: 6186bef751ef9ad9510cef50b875b9fd89ff1c74fd6b6ed960d2cb346538dbab
tags: []
tickers: []
---
Decider policy version 14 (config 9ea09b9as, prompt_versions#581, created 2026-08-04 08:22:22 by prompt_lab [human] — v14 Decider (auto) · feedback#1245 · success 51.9% · 52 trades · 2026-08-04 15:17 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 13 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).