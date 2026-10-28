---
id: DA.root
version: DeciderAgent.9ea09b9as.v59
agent: DeciderAgent
title: "Decider policy v59"
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
body_sha256: fea314c2cfe607ffa5fa0b28c668786dbb6d0cbe1fc7b525baa0e33f881bcfa2
tags: []
tickers: []
---
Decider policy version 59 (config 9ea09b9as, prompt_versions#661, created 2026-10-28 09:38:30 by codex_operator [codex_operator] — Operator policy correction: reconcile selective half-size regime/macro entries; preserve candidate-level stops, earnings exclusions and account rails). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 18 code-owned block(s), 42 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).