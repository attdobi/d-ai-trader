---
id: DA.root
version: DeciderAgent.9ea09b9as.v26
agent: DeciderAgent
title: "Decider policy v26"
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
body_sha256: eff27dffcddb7f4b1799b2aaeda11cd7d5aa41cbc4afadb2e71c188dc14dcac5
tags: []
tickers: []
---
Decider policy version 26 (config 9ea09b9as, prompt_versions#612, created 2026-09-04 10:59:37 by claude_code [claude_code] — v26 Decider (claude_code 2026-09-04) · user template only: "cited" is REQUIRED on every decision (1-4 bare ids from the GUIDELINE INDEX) — directives/soul/memory unchanged from v25). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 27 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).