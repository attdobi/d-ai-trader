---
id: DA.root
version: DeciderAgent.9ea09b9as.v61
agent: DeciderAgent
title: "Decider policy v61"
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
body_sha256: fc9d1ae889706d3066ff4bb69832805be26586c1f8036be086a0ee2ca1bf38eb
tags: []
tickers: []
---
Decider policy version 61 (config 9ea09b9as, prompt_versions#667, created 2026-10-29 09:52:50 by codex_operator [codex_operator] — Add original screenshot context and evidence-scoped editorial-framing observations; preserve approved trading controls and require reviewed evaluation before promoting a signal.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 19 code-owned block(s), 50 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).