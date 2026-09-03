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
body_sha256: f5445aee85cbfe751ce0feb3114078b05b30986ebba92895ae389c842fb1e85c
tags: []
tickers: []
---
Company extraction policy version 0 (config 9ea09b9as, prompt_versions#548, created 2026-04-27 10:06:51 by init_database [seed] — Extracts companies (rolled up to parent) and ticker symbols from summarizer output). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: empty; soul: inherited from agents/company/SOUL.default.md; memory: inherited from agents/company/MEMORY.default.md. Overlays: 0 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.extract_companies_from_summaries): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the cycle's summaries filled in. Its tickers seed the market-trends recap and the Decider's graph query (route 'entities').