---
id: DA.directives.loser_management
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "🚨 LOSER MANAGEMENT — NO DEFAULT “HOLD ALL”"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 12
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n\n"
body_sha256: 4a61e71bfb645b344e6b75a81248e6958f86026948b42537ecb114b8523524ba
tags: []
tickers: []
---
🚨 LOSER MANAGEMENT — NO DEFAULT “HOLD ALL”
- Any position ≤ -4% vs cost is a default SELL/trim unless you can cite a fresh (≤1 session) catalyst; spell it out. “Hold to mean revert” without a catalyst is invalid.
- If ALL holdings are red and no catalysts are present, you MUST SELL at least the weakest name to recycle risk; do not return an all-HOLD slate.
- Stale positions (no catalyst in summaries/momentum recap) should be trimmed/exited to free cash and reduce drag.