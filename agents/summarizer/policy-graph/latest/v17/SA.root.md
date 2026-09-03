---
id: SA.root
version: SummarizerAgent.9ea09b9as.v17
agent: SummarizerAgent
title: "Summarizer policy v17"
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
body_sha256: a5d047c8d2677bf563aedb9f5cca9fc191d7cf9dee1927f2fe85e691e1a5ca46
tags: []
tickers: []
---
Summarizer policy version 17 (config 9ea09b9as, prompt_versions#600, created 2026-09-02 14:57:20 by claude_code [claude_code] — v17 Summarizer (claude_code 2026-09-02) · regime-first insights, crowding/extension + event-risk flags, compact card (Decider reads only headlines+insights)). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.