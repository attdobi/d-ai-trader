---
id: FA.memory.log.2026_09_02_meta_2
version: FeedbackAgent.9ea09b9as.v8
agent: FeedbackAgent
title: "2026-09-02 #meta #policy-persistence"
node_type: entry
polarity: evidence
polarity_source: heuristic
parent: FA.memory
field: memory
order: 9
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#601
sep_before: ""
sep_after: "\n\n"
body_sha256: a9fc12a0163230433339532210c0784484ab1d4a695551888eb62805423f0d44
tags: [meta, policy-persistence]
tickers: []
---
## 2026-09-02 #meta #policy-persistence
- **What happened:** the weekly AUTO path replaced strategy_directives with a 500-char truncated reminder and blanked soul/memory. Human-approved Decider v14 lived 2 days, v18 lived 6 days; every realized-outcome measurement scored a policy that was no longer active.
- **Lesson:** before attributing an outcome to a shipped change, verify the change was still ACTIVE for the window. Fixed 2026-09-02 (reminder is appended; soul/memory carried forward).