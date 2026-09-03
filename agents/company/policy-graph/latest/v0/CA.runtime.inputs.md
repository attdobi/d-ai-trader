---
id: CA.runtime.inputs
version: CompanyExtractionAgent.9ea09b9as.v0
agent: CompanyExtractionAgent
title: "Per-cycle runtime inputs"
node_type: data
polarity: structure
polarity_source: override
parent: CA.root
field: null
order: 0
owner: runtime
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: a70c188e1fc36fea11028d8d4ddbf80dc8913cbb5d8b368ddb3d93a6fe4eb8b2
tags: []
tickers: []
---
Per-cycle data blocks — not policy text; varies per cycle.

Placeholders filled by safe_format_template from the user prompt template:
- {summaries}

Blocks supplied by decider_agent.extract_companies_from_summaries every cycle: the Summarizers' headlines and insights (about six summaries), one block per summarizer.