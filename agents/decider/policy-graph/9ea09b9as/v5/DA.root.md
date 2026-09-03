---
id: DA.root
version: DeciderAgent.9ea09b9as.v5
agent: DeciderAgent
title: "Decider policy v5"
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
body_sha256: 879313d865757a467e73f48b3f92a1c173cda61e9c0de699ec2fb926b7e3613b
tags: []
tickers: []
---
Decider policy version 5 (config 9ea09b9as, prompt_versions#562, created 2026-06-24 16:18:57 by prompt_lab [human] — v5 Decider (auto) · feedback#1235 · success 25.0% · 20 trades · 2026-06-24 22:27 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).