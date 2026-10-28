---
id: FA.code.json_format
version: code@f42dce4ea4f4
agent: FeedbackAgent
title: "Feedback JSON format (code)"
node_type: code
polarity: structure
polarity_source: override
parent: FA.code
field: null
order: 3
owner: code
status: read-only
compiled: never
locked: true
provenance: feedback_agent.py:_generate_ai_feedback
sep_before: ""
sep_after: ""
body_sha256: 514f333e45b803e38e2b6208c69a2cb892e10270da21ee0e1e8c15abb6e84728
tags: []
tickers: []
source_file: feedback_agent.py
source_symbol: _generate_ai_feedback:FEEDBACK_JSON_FORMAT
code_sha: f42dce4ea4f4
condition: null
fires: true
position: user_prompt_tail
---
Return ONLY one valid JSON object with these existing keys:
{
    "largest_measured_leak": {"name": "evidenced issue or unavailable", "usd": null, "evidence": "scope, supplied numbers and uncertainty"},
    "regime_read": "observed comparison or unavailable",
    "decider_rules": [],
    "decider_feedback": "Nonbinding research summary for review, at most 900 characters; approved risk limits remain authoritative.",
    "summarizer_rules": [],
    "summarizer_feedback": "Nonbinding context-quality findings for review, at most 600 characters; preserve the schema.",
    "key_insights": ["evidence-scoped finding, uncertainty or separate evaluation plan"],
    "timing_patterns": "supported finding or unavailable",
    "risk_management": "supported finding or unavailable",
    "sector_insights": "supported finding or unavailable"
}
Use supplied dollars for usd, otherwise null. decider_rules accepts 0-2 proposals; summarizer_rules 0-1. Empty arrays mean no supported change. Each compact proposal is at most 220 characters, with one observable condition and one action. Label changed behavior as a proposal. Put its predeclared outcome, sample requirement, matched comparator and exact horizon in key_insights. Never manufacture findings or fill a rule quota. No Markdown, code fences or prose outside JSON.