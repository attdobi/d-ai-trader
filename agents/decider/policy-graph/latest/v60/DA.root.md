---
id: DA.root
version: DeciderAgent.9ea09b9as.v60
agent: DeciderAgent
title: "Decider policy v60"
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
body_sha256: 84a3c8517089be8c4c0319c133cab992455d203ec782e1fb5d469a53894d8370
tags: []
tickers: []
---
Decider policy version 60 (config 9ea09b9as, prompt_versions#664, created 2026-10-28 14:45:32 by codex_operator [codex_operator] — Operator audit 2026-10-28: readable approved rules, evidence-grounded learning, and a capped pre-earnings strategy.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 18 code-owned block(s), 50 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).