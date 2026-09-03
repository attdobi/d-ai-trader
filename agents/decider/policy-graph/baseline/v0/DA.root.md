---
id: DA.root
version: DeciderAgent.baseline.v0
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
body_sha256: 1d0b08168a1a8ff5ae33d8039c9477f3e2ba4f55be1613c613300aa239257f6d
tags: []
tickers: []
---
Decider policy version 0 (config baseline, prompt_versions#0, created 2026-01-01 00:00:00 by init_database [seed] — v0 baseline DeciderAgent — committed with the repository). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).