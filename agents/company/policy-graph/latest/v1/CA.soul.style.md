---
id: CA.soul.style
version: CompanyExtractionAgent.9ea09b9as.v1
agent: CompanyExtractionAgent
title: Style
node_type: section
polarity: gate
polarity_source: heuristic
parent: CA.soul
field: soul
order: 4
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#663
sep_before: ""
sep_after: "\n"
body_sha256: 835a17f2477d454b1d4753a611f36f456fa90d10142272ec7dc94aff3aa64238
tags: []
tickers: []
---
## Style
Include each evidenced company once. Prefer an empty symbol to a guessed ticker. Do not silently switch GOOG and GOOGL or invent a similar issuer. Output only the existing company/symbol JSON array.