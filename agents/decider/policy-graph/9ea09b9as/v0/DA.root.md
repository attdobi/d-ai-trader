---
id: DA.root
version: DeciderAgent.9ea09b9as.v0
agent: DeciderAgent
title: "Decider policy v0"
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
body_sha256: 1d4b8f67d6549a92086596ec741ed13d28c31292e8957cdb3fadd63734e4cd61
tags: []
tickers: []
---
Decider policy version 0 (config 9ea09b9as, prompt_versions#547, created 2026-08-03 08:17:21 by init_database [seed] — DeciderAgent — profit-harvesting first, rotation second; enforces contrarian crowd-fade behavior and compact JSON output.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 15 code-owned block(s), 13 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).