---
id: CA.root
version: CompanyExtractionAgent.9ea09b9as.v0
agent: CompanyExtractionAgent
title: "Company extraction policy v0"
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
body_sha256: c9c2819eb7ada016337dbbf3eccfa3740a95cc9ebea74a50cdac1a6c35d23855
tags: []
tickers: []
---
Company extraction policy version 0 (config 9ea09b9as, prompt_versions#548, created 2026-04-27 10:06:51 by init_database [seed] — Extracts companies (rolled up to parent) and ticker symbols from summarizer output). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: empty; soul: stored; memory: stored. Overlays: 0 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.extract_companies_from_summaries): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the cycle's summaries filled in. Its tickers seed the market-trends recap and the Decider's graph query (route 'entities').