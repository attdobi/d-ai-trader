---
id: DA.directives.large_selloff_review
version: DeciderAgent.9ea09b9as.v63
agent: DeciderAgent
title: "Large selloff review"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 20
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#673
sep_before: ""
sep_after: "\n"
body_sha256: bb02c4eca19b6a596e83ef2d1832a6cdc6a302fd9c6700b9693a34ee127c6d49
tags: []
tickers: []
---
## Large selloff review
For every ticker in LARGE SELLOFF REVIEW, include one considered row with a buy, watch or reject verdict, including names under re-entry quarantine. Use decision-time evidence to explain how the stock moved relative to its sector and whether support held. Cite the binding guideline. For a watch or rejection, state what would justify another review, such as the quarantine ending or a supported reclaim. For a buy, give the supported entry and stop. Apply [[Re-entry quarantine]], [[Day chase]] and [[Priced kill]] along with the other active controls. Inclusion on this list only requires an assessment.