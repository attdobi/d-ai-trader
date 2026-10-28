---
id: FA.template.user
version: FeedbackAgent.baseline.v0
agent: FeedbackAgent
title: "User prompt template"
node_type: template
polarity: structure
polarity_source: override
parent: FA.root
field: user_prompt_template
order: 0
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#0
sep_before: ""
sep_after: ""
body_sha256: 09fbc7452a5b454d3f29899ce21609c394754fe6d13a81dfda9fd466ce9e42ab
tags: []
tickers: []
---
Review this supplied evidence without inventing missing facts.

Context Data:
{context_data}

Performance Metrics:
{performance_metrics}

State the population, period, sample coverage and uncertainty of material findings. Distinguish realized results, paper marks, replays, model actions and actual fills. Keep the earnings reporter separate from peers, and distinguish ordinary entries, the approved capped earnings-event strategy and post-release trades when the evidence supports the split.

Return one valid JSON object with these existing keys:
{{
  "largest_measured_leak": {{
    "name": "evidenced issue or unavailable",
    "usd": null,
    "evidence": "scope, supplied numbers and uncertainty"
  }},
  "regime_read": "observed comparison or unavailable",
  "decider_rules": [],
  "decider_feedback": "At most 900 characters: supported process guidance subordinate to approved policy.",
  "summarizer_rules": [],
  "summarizer_feedback": "At most 600 characters: evidence to surface, preserving its schema.",
  "key_insights": [
    "evidence-scoped finding or unavailable"
  ],
  "timing_patterns": "supported finding or unavailable",
  "risk_management": "supported finding or unavailable",
  "sector_insights": "supported finding or unavailable"
}}

Use supplied dollars for usd when available, otherwise null. Rule arrays may be empty; do not manufacture changes to satisfy a quota. Offer at most one primary and one secondary Decider proposal, and one primary Summarizer proposal. Each compact rule is <=220 characters with one clear condition/action; label changed behavior as a proposal. Put the separate sample, horizon and comparison in key_insights. Do not silently weaken stops, increase caps, ban every opportunity in a regime or liquidate all holdings because of a calendar event. JSON only.