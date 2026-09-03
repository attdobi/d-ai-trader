---
id: DA.root
version: DeciderAgent.9ea09b9as.v22
agent: DeciderAgent
title: "Decider policy v22"
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
body_sha256: 5823e68c51d9026d26ed3a29b211bdd1fc557e409843a096e00aba393bd1216c
tags: []
tickers: []
---
Decider policy version 22 (config 9ea09b9as, prompt_versions#602, created 2026-09-02 20:29:22 by claude_code [claude_code] — v22 Decider (claude_code 2026-09-03) · user template only: allow the optional "cited" guideline-id list per decision (policy graph citations) — directives/soul/memory unchanged from v21). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 23 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).