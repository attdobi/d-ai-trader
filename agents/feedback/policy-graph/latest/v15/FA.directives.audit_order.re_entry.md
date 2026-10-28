---
id: FA.directives.audit_order.re_entry
version: FeedbackAgent.9ea09b9as.v15
agent: FeedbackAgent
title: RE-ENTRY
node_type: rule
polarity: gate
polarity_source: heuristic
parent: FA.directives.audit_order
field: strategy_directives
order: 7
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#662
sep_before: ""
sep_after: "\n"
body_sha256: 4719a77153af6fbffa2cd80761f7ecead10bd9c44effa34e6902edee903df9cf
tags: []
tickers: []
---
4. RE-ENTRY: same-ticker entries within 3 days of an exit are scored separately. If they lose, the rule is a quarantine with the number attached.