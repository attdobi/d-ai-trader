---
id: DA.root
version: DeciderAgent.9ea09b9as.v23
agent: DeciderAgent
title: "Decider policy v23"
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
body_sha256: 101f56688bdaef114e47bd5846177f8ab49ae5060a42f2650df143cf98d55f4b
tags: []
tickers: []
---
Decider policy version 23 (config 9ea09b9as, prompt_versions#603, created 2026-09-02 20:30:30 by policy_graph [rl_loop] — v23 Decider (policy graph proposal #1) · edit DA.directives.strategy.priced_kill: Makes a numeric kill an explicit first-priority full SELL on the first supplied-price breach rather than only an entry annotation. · 1 of 1 guideline files approved). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 16 code-owned block(s), 23 long-term memory row(s). Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when the placeholder is absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, plus the long-term memory rows (decider_memory).