---
id: CA.directives.parent_ticker_resolution
version: CompanyExtractionAgent.9ea09b9as.v1
agent: CompanyExtractionAgent
title: "Parent and ticker resolution"
node_type: section
polarity: mixed
polarity_source: heuristic
parent: CA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#663
sep_before: ""
sep_after: "\n\n"
body_sha256: 4ba637fc582a508768a44f2e74f627597231610aa394c73106aa728ae3988662
tags: []
tickers: []
---
## Parent and ticker resolution
Parent relationships can change; use supported mappings. Preserve a valid supplied share class, uppercase symbols, and deduplicate parent companies. Leave uncertain symbols empty.