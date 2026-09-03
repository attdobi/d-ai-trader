---
id: CA.soul.style
version: CompanyExtractionAgent.9ea09b9as.v0
agent: CompanyExtractionAgent
title: Style
node_type: section
polarity: principle
polarity_source: heuristic
parent: CA.soul
field: soul
order: 4
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#548
sep_before: ""
sep_after: ""
body_sha256: cdec4a85ff9379a717eabc096e935fa476b7ce51812a2e57cec0ab021e68ffa6
tags: []
tickers: []
---
## Style
- Precision over recall on tickers: leave `symbol` empty rather than guess.
- Recall over precision on companies: every named company, product or brand is listed once.
- Uppercase tickers, no duplicates, JSON only.