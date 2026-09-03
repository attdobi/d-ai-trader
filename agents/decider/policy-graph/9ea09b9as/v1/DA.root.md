---
id: DA.root
version: DeciderAgent.9ea09b9as.v1
agent: DeciderAgent
title: "Decider policy v1"
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
body_sha256: 97cc38d621f2b5947126aef66421a4c5fd22865331c8d88af0edf0381ec4b50f
tags: []
tickers: []
---
Decider policy version 1 (config 9ea09b9as, prompt_versions#551, created 2026-06-18 17:31:48 by system [weekly] — Strategy updated from feedback (ID: 1233)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/decider/SOUL.default.md; memory: stored. Overlays: 15 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).