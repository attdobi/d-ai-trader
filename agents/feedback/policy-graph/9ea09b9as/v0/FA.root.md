---
id: FA.root
version: FeedbackAgent.9ea09b9as.v0
agent: FeedbackAgent
title: "Feedback policy v0"
node_type: root
polarity: structure
polarity_source: override
parent: null
field: null
order: 0
owner: generated
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: 513ea13cc70aecd5ac2d733de97c9145c5e11baaef18032964fd30957f5e0afd
tags: []
tickers: []
---
Feedback policy version 0 (config 9ea09b9as, prompt_versions#549, created 2026-06-25 13:22:55 by init_database [seed] — feedback_analyzer — concise, rule-driven EOD reviewer (~300 words) producing two deterministic snippet lines.). Fields: system_prompt: stored; user_prompt_template: stored; strategy_directives: stored; soul: stored; memory: inherited from agents/feedback/MEMORY.default.md. Overlays: 3 code-owned block(s), 0 long-term memory row(s). Runtime assembly (feedback_agent._generate_ai_feedback): only the soul is injected ('## AGENT IDENTITY' after the hardcoded system base); the stored templates, strategy_directives and memory are not executed by the weekly path.