---
id: FA.code.json_format
version: code@062f5ef0d69f
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
body_sha256: 7a1d216c4420b7c594fe3a8e448de1fa8ea1e1ec4f4e49e78b36ebeda2d99d06
tags: []
tickers: []
source_file: feedback_agent.py
source_symbol: _generate_ai_feedback:FEEDBACK_JSON_FORMAT
code_sha: 062f5ef0d69f
condition: null
fires: true
position: user_prompt_tail
---

🚨 CRITICAL JSON REQUIREMENT:
Return ONLY valid JSON in this EXACT format:
{
    "largest_measured_leak": {"name": "one phrase", "usd": -123.0, "evidence": "one sentence with the numbers"},
    "regime_read": "RISK-ON | MIXED | RISK-OFF — one sentence on what the regime did to the rules",
    "decider_rules": ["trigger → action → falsification metric", "second rule", "optional third", "optional fourth"],
    "decider_feedback": "REGIME: … | ENTRY: … | KILL: … | RE-ENTRY: … | HARVEST: … — one clause per rule, ≤ 900 characters total, no narrative",
    "summarizer_rules": ["trigger → what context to surface → metric", "optional second"],
    "summarizer_feedback": "≤ 600 characters: the CONTEXT the Summarizer must surface next (index/leader regime, sector-ETF direction, extension/crowding of the names it headlines, scheduled-event risk, coordinated-coverage flags). Do not redesign its schema.",
    "key_insights": ["five one-sentence findings, each carrying a number from the diagnostics"],
    "timing_patterns": "entry/exit timing finding with numbers",
    "risk_management": "kill geometry / sizing finding with numbers",
    "sector_insights": "correlation / sector finding with numbers"
}
Limits: decider_rules 2-4 items and summarizer_rules 1-3 items, each ≤ 220 characters, each a single trigger → action → metric rule.

⛔ NO explanatory text ⛔ NO markdown ⛔ NO code blocks
✅ ONLY pure JSON starting with { and ending with }