---
id: DA.root
version: DeciderAgent.9ea09b9as.v63
agent: DeciderAgent
title: "Decider policy v63"
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
body_sha256: 69faa29c49fe365d48afa7c338abc48b8cc2b799abd5d3a2faae5c6e8dfb5e3c
tags: []
tickers: []
---
Decider policy version 63 (config 9ea09b9as, prompt_versions#673, created 2026-11-23 07:56:46 by codex_operator [codex_operator] — Explain each large selloff assessment, the binding rule and when to revisit it.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 20 code-owned block(s), 51 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).