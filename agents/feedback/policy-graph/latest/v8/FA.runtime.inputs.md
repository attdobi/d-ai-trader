---
id: FA.runtime.inputs
version: FeedbackAgent.9ea09b9as.v8
agent: FeedbackAgent
title: "Per-cycle runtime inputs"
node_type: data
polarity: structure
polarity_source: override
parent: FA.root
field: null
order: 0
owner: runtime
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: 67ae5bc9b57721990c70202916de0bbecf95c499918b928713d091ca3ec3ff95
tags: []
tickers: []
---
Per-cycle data blocks — not policy text; varies per cycle.

Placeholders filled by safe_format_template from the user prompt template:
- {context_data}
- {performance_metrics}

Blocks supplied by feedback_agent._generate_ai_feedback: closed-trade sample, computed diagnostics, current prompts of the other agents, prior feedback.