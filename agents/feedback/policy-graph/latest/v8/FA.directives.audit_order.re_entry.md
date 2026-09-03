---
id: FA.directives.audit_order.re_entry
version: FeedbackAgent.9ea09b9as.v8
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
provenance: prompt_versions#601
sep_before: ""
sep_after: "\n"
body_sha256: 92ec5f973350d575cf96f524d023e97a99f08cf13f0f2b911091f6b11915a616
tags: []
tickers: []
---
4. RE-ENTRY: same-ticker entries within 3 days of an exit are scored separately (33% win / −$118 versus 54% / +$179 for spaced entries, Jul–Sep 2026). If they lose, the rule is a quarantine with the number attached.