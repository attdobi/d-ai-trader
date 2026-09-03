---
id: CA.root
version: CompanyExtractionAgent.baseline.v0
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
body_sha256: 11237d41367383115aa974e55d353c506ab2954cb2cac27aacdeb45534036378
tags: []
tickers: []
---
Company extraction policy version 0 (config baseline, prompt_versions#0, created 2026-01-01 00:00:00 by init_database [seed] — v0 baseline CompanyExtractionAgent — committed with the repository). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: empty; soul: stored; memory: stored. Overlays: 0 code-owned block(s), 0 long-term memory row(s). Runtime assembly (decider_agent.extract_companies_from_summaries): system prompt = system_prompt template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the cycle's summaries filled in. Its tickers seed the market-trends recap and the Decider's graph query (route 'entities').