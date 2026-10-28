---
id: CA.root
version: CompanyExtractionAgent.9ea09b9as.v1
agent: CompanyExtractionAgent
title: "Company extraction policy v1"
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
body_sha256: a988f863f39c0353717455204ca5b38164acf8d59d9a5ad40e2eb3372bb7a44a
tags: []
tickers: []
---
Company extraction policy version 1 (config 9ea09b9as, prompt_versions#663, created 2026-10-28 14:45:32 by codex_operator [codex_operator] — Operator audit 2026-10-28: readable approved rules, evidence-grounded learning, and a capped pre-earnings strategy.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: stored. Overlays: 0 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.extract_companies_from_summaries): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the cycle's summaries filled in. Its tickers seed the market-trends recap and the Decider's graph query (route 'entities').