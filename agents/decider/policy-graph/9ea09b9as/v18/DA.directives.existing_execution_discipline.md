---
id: DA.directives.existing_execution_discipline
version: DeciderAgent.9ea09b9as.v18
agent: DeciderAgent
title: "Existing execution discipline"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 8
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#592
sep_before: ""
sep_after: ""
body_sha256: 20049cbfce3575edadb23121171cb9d2b23cab8ecc651bfc0d9c7c6ba5a9b78c
tags: []
tickers: []
---
## Existing execution discipline
- Harvest profitable positions that are extended, stale, or no longer supported by fresh price confirmation; profits are realized only when sold.
- Cut thesis-broken, stale, and unvalidated inherited inventory without averaging down.
- Reject headline-only setups and vertical post-pop chases.
- Cash is a valid decision when inventory has been triaged and no candidate clears the quality gate.
- Rank candidates R1..Rk only after they clear all portfolio, funds, cap, and setup-quality constraints.