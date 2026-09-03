---
id: DA.root
version: DeciderAgent.9ea09b9as.v18
agent: DeciderAgent
title: "Decider policy v18"
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
body_sha256: 5e1eeee253f0627ecb2bf5684aabf32492403e99f09de40499369a62b0aa8869
tags: []
tickers: []
---
Decider policy version 18 (config 9ea09b9as, prompt_versions#592, created 2026-08-21 16:08:37 by prompt_lab [human] — v18 Decider (auto) · feedback#1249 · success 62.2% · 45 trades · 2026-08-21 22:48 UTC · partial: system_prompt+user_prompt_template+strategy_directives+soul). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 16 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).