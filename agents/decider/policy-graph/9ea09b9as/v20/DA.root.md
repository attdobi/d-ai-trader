---
id: DA.root
version: DeciderAgent.9ea09b9as.v20
agent: DeciderAgent
title: "Decider policy v20"
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
body_sha256: 9e7673eea485a975d65c4119385aa48631071345c44530071454ae1c023c4258
tags: []
tickers: []
---
Decider policy version 20 (config 9ea09b9as, prompt_versions#597, created 2026-09-01 18:38:15 by prompt_lab [human] — v20 Decider (auto) · feedback#1251 · success 49.1% · 55 trades · 2026-09-01 20:28 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 17 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).