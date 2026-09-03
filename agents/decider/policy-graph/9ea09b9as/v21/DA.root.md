---
id: DA.root
version: DeciderAgent.9ea09b9as.v21
agent: DeciderAgent
title: "Decider policy v21"
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
body_sha256: 4254422583ac440a7d99e0b9d8f0736ea3da99ce38cbb162153134677411a632
tags: []
tickers: []
---
Decider policy version 21 (config 9ea09b9as, prompt_versions#599, created 2026-09-02 14:57:20 by claude_code [claude_code] — v21 Decider (claude_code 2026-09-02) · regime gate + extension cap ≤5%/8% + priced kill K:<price>;D:<%> + 2-session re-entry quarantine + correlation cap · from population diagnostics (79 campaigns, Jul 1–Sep 2)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 15 code-owned block(s), 23 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).