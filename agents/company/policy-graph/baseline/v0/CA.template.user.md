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
body_sha256: 710de1d6bb083b8e4615990d6f564d2e5c77c69c1c73ad17fcfbbecfe5f1619b
tags: []
tickers: []
---
Identify every company, product, or brand referenced in the following market summaries. When a product or subsidiary is mentioned, map it to the publicly traded parent company before assigning the ticker. If you are unsure of a ticker symbol, return an empty string for that entry.

Summaries:
{summaries}

Return ONLY a JSON array like:
[
  {{ "company": "Alphabet", "symbol": "GOOGL" }},
  {{ "company": "The Walt Disney Company", "symbol": "DIS" }}
]

No explanation, no markdown, just JSON.