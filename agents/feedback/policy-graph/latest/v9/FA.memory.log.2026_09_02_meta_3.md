---
id: FA.memory.log.2026_09_02_meta_3
version: FeedbackAgent.9ea09b9as.v9
agent: FeedbackAgent
title: "2026-09-02 #meta #dead-prompt"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: FA.memory
field: memory
order: 10
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#608
sep_before: ""
sep_after: "\n\n"
body_sha256: 12eb522bf079ba1b84899fae30a331b25b92f7761aa3da6135dc501b002126de
tags: [meta, dead-prompt]
tickers: []
---
## 2026-09-02 #meta #dead-prompt
- **What happened:** my evolved system_prompt / user_prompt_template were never executed by the weekly path — only the soul is injected. Three approved FeedbackAgent versions changed nothing but the soul.
- **Lesson:** verify the code path consumes a field before evolving it; put the lesson where it executes (soul, and the hardcoded weekly prompt).