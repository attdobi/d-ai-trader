---
id: CA.template.user
version: CompanyExtractionAgent.baseline.v0
agent: CompanyExtractionAgent
title: "User prompt template"
node_type: template
polarity: structure
polarity_source: override
parent: CA.root
field: user_prompt_template
order: 0
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: ""
body_sha256: a26c2f0bf656dcfb568f4554aeffe42b7810e40ceeb834d51c28fbb74cf0e674
tags: []
tickers: []
---
Identify every company, product or brand actually referenced in these summaries. Roll up to a listed parent only when supported. Preserve an explicitly supplied valid share-class ticker; leave symbol empty if uncertain. Deduplicate repeated mentions. ETFs and indexes are not companies. A peer's earnings announcement does not establish another company's reporting date.

Summaries:
{summaries}

Return ONLY this JSON array shape:
[
  {{ "company": "Alphabet", "symbol": "GOOGL" }},
  {{ "company": "The Walt Disney Company", "symbol": "DIS" }}
]
Use actual evidenced companies; these are format examples, not required output. No Markdown or explanation.