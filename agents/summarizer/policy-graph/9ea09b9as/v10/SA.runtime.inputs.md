---
id: SA.runtime.inputs
version: SummarizerAgent.9ea09b9as.v10
agent: SummarizerAgent
title: "Per-cycle runtime inputs"
node_type: data
polarity: structure
polarity_source: override
parent: SA.root
field: null
order: 0
owner: runtime
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: fd90a349dc7e37bf1562b20aa7a96df860cf0a9a5199f87abb544d01aae7d0f3
tags: []
tickers: []
---
Per-cycle data blocks — not policy text; varies per cycle.

Placeholders filled by safe_format_template from the user prompt template:
- {feedback_context}
- {content}

Blocks supplied by main.get_openai_summary every cycle: article text / screenshots, portfolio holdings snapshot, PERFORMANCE FEEDBACK from the latest feedback row.