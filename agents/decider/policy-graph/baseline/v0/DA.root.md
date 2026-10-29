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
body_sha256: 18826e871ab7de22f36f5e02cb9945a4ac702759a65cb531677b87f0733e3a26
tags: []
tickers: []
---
Decider policy version 0 (config baseline, prompt_versions#0, created 2026-01-01 00:00:00 by init_database [seed] — v0 baseline DeciderAgent — committed with the repository). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 19 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).