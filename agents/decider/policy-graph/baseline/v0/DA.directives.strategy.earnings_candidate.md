---
id: DA.directives.strategy.earnings_candidate
version: DeciderAgent.baseline.v0
agent: DeciderAgent
title: "EARNINGS CANDIDATE"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: DA.directives.strategy
field: strategy_directives
order: 12
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: "\n"
body_sha256: 9f1032ddf3e309407b128f186d27e6a8570f7b21b0c9818033212d9e1059dea3
tags: []
tickers: []
---
10. EARNINGS CANDIDATE — For the standard strategy, reject a candidate whose own earnings release is within the next 5 trading sessions; state the verified date and that it lies inside the hold window. A separately approved earnings_event BUY is allowed only under the verified supplied event contract and all of its hard caps. A post-release opportunity uses the standard strategy once the completed release and price response are confirmed.