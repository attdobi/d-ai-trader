---
id: DA.directives.setup_specific_kill_discipline
version: DeciderAgent.9ea09b9as.v14
agent: DeciderAgent
title: "Setup-Specific Kill Discipline"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 3
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#581
sep_before: ""
sep_after: "\n\n"
body_sha256: 6b691d414d855cf0da2cb3139b9a814084c59b4325f9a9ad4e0fcdb458beeee4
tags: []
tickers: []
---
## Setup-Specific Kill Discipline
- Every new BUY must state a compact, objective kill criterion in its reason, using `K:` after the R-rank and setup evidence. The kill may be a named technical invalidation (for example, a 20d/support break) and/or an explicitly stated percentage. It must be specific enough for a later decision cycle to test.
- Do not replace setup-specific invalidation with a universal fixed percentage. If a percentage kill is chosen, state that exact percentage; if a technical kill is chosen, state the technical condition. Do not retroactively invent a numerical stop for an inherited position or a legacy position whose recorded entry criterion is unavailable.
- When current data shows that a holding has reached its recorded kill criterion or the stated technical invalidation, SELL rather than HOLD and do not silently widen the criterion. If the data only show that the exit occurred beyond the criterion, report the current observed facts without inventing a cause such as a gap, liquidity event, or stop breach.
- This targets the directly documented mismatch between stated and realized risk: ZS was sold at -4.9% after a stated -2%/20d stop, and TMO was sold at -4.8% after a stated -1.5%/20d exit. It is not evidence for imposing the same stop on every setup.