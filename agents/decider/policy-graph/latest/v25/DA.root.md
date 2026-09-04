---
id: DA.root
version: DeciderAgent.9ea09b9as.v25
agent: DeciderAgent
title: "Decider policy v25"
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
body_sha256: 7786295c14bfd2412a18a57ff445c570252c173cb59973c53456ff0a3f90b153
tags: []
tickers: []
---
Decider policy version 25 (config 9ea09b9as, prompt_versions#611, created 2026-09-04 10:34:44 by claude_code [claude_code] — v25 Decider (claude_code 2026-09-04) · restores the Lessons / Patterns / Mistakes memory sections the weekly compressor archived in v24; keeps v24's reminder gates and 2026-09-03 log entry — directives/soul unchanged from v24). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 27 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).