---
id: DA.root
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "Decider policy v58"
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
body_sha256: bdf1b31042f7ccd883559f563f99af4f39cff4d44767521bd7b46f8f77d9b437
tags: []
tickers: []
---
Decider policy version 58 (config 9ea09b9as, prompt_versions#660, created 2026-10-28 08:59:10 by prompt_lab [human] — reduce hold cash decisions - update to system prompt). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 17 code-owned block(s), 42 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).