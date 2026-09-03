---
id: SA.root
version: SummarizerAgent.9ea09b9as.v13
agent: SummarizerAgent
title: "Summarizer policy v13"
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
body_sha256: b33bdf4b92fe0c0d4125ee26e0b450d77b5a2c3043657b58ad19caff9a66d6ae
tags: []
tickers: []
---
Summarizer policy version 13 (config 9ea09b9as, prompt_versions#589, created 2026-08-20 17:33:09 by system [weekly] — Strategy updated from feedback (ID: 1248)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: inherited from agents/summarizer/SOUL.default.md; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.