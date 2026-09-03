---
id: DA.root
version: DeciderAgent.9ea09b9as.v4
agent: DeciderAgent
title: "Decider policy v4"
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
body_sha256: 9edbda4ef888f0fca741f9c226d999a470f59a74e9053081f1fb485b6ca58f79
tags: []
tickers: []
---
Decider policy version 4 (config 9ea09b9as, prompt_versions#559, created 2026-06-20 09:05:36 by prompt_lab [human] — v2 Decider (auto) · feedback#1234 · success 29.4% · 17 trades · 2026-06-20 16:03 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).