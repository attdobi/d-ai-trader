---
id: DA.root
version: DeciderAgent.9ea09b9as.v11
agent: DeciderAgent
title: "Decider policy v11"
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
body_sha256: 1f081d5a985a0a1eb671d731bc2e5f8f298e8f6d4d4e5cc03bc7597f8af065ea
tags: []
tickers: []
---
Decider policy version 11 (config 9ea09b9as, prompt_versions#577, created 2026-07-16 17:31:44 by system [weekly] — Strategy updated from feedback (ID: 1241)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/decider/SOUL.default.md; memory: stored. Overlays: 16 code-owned block(s), 10 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).