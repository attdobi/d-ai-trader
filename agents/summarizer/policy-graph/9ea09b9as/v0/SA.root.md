---
id: SA.root
version: SummarizerAgent.9ea09b9as.v0
agent: SummarizerAgent
title: "Summarizer policy v0"
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
body_sha256: 497309d822f28be95b3b684314dbedf5e9baeac6667525553fc7d7d36ea5eeeb
tags: []
tickers: []
---
Summarizer policy version 0 (config 9ea09b9as, prompt_versions#546, created 2026-08-03 08:17:21 by init_database [seed] — SummarizerAgent — aggressive, image-first narrative (~200 words) with ticker-centric headlines and a final Watchlist, same JSON shape). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 1 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.