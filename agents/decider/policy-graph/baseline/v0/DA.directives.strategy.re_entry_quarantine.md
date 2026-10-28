---
id: DA.directives.strategy.re_entry_quarantine
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "RE-ENTRY QUARANTINE"
node_type: rule
polarity: gate
polarity_source: override
parent: DA.directives.strategy
field: strategy_directives
order: 6
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: ec953d1f2ef04ca269fd9f003a9d7d75e2a545d653675d7237ec5859de511fb3
tags: []
tickers: []
---
4. RE-ENTRY QUARANTINE — Do not BUY a ticker on QUARANTINE or one exited within the last 2 trading sessions. After a losing exit, also require a reclaim of the failed level or a genuinely new catalyst. This additional evidence does not waive the 2-session quarantine.