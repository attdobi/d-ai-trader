---
id: DA.root
version: DeciderAgent.9ea09b9as.v7
agent: DeciderAgent
title: "Decider policy v7"
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
body_sha256: 2baf41686172b7222a183e7d11d92741b6a8740982a5140c14f5235d0484430b
tags: []
tickers: []
---
Decider policy version 7 (config 9ea09b9as, prompt_versions#568, created 2026-06-25 08:46:19 by prompt_lab [human] — v7 Decider (auto) · feedback#1237 · success 25.0% · 20 trades · 2026-06-25 15:42 UTC). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).