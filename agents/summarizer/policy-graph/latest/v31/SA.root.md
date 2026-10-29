---
id: SA.root
version: SummarizerAgent.9ea09b9as.v31
agent: SummarizerAgent
title: "Summarizer policy v31"
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
body_sha256: 9648757261b581d6a805002a2cfe5cb93fa07171b1bffe5bb6cd0383e085086a
tags: []
tickers: []
---
Summarizer policy version 31 (config 9ea09b9as, prompt_versions#669, created 2026-10-29 09:52:50 by codex_operator [codex_operator] — Add original screenshot context and evidence-scoped editorial-framing observations; preserve approved trading controls and require reviewed evaluation before promoting a signal.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 2 code-owned block(s), 0 long-term memory row(s). Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.