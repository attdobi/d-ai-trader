---
id: DA.code.justification_detail
version: code@3674eb0468b4
agent: DeciderAgent
title: "JUSTIFICATION DETAIL"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 9
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 9a3742cdc0ce9727cef4b508ce5d523cc2964475d841f324307458094619f556
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#2"
code_sha: 3674eb0468b4
condition: null
fires: true
position: user_prompt_tail
---


JUSTIFICATION DETAIL (for human + RLHF review — overrides any shorter length cap): Make every "reason" (and the "cash_reason") a specific, self-contained justification of roughly 220-450 characters that a reviewer could audit without other context. Each MUST cover, with concrete numbers: (1) CATALYST — what changed and why it is fresh, not a stale/extended headline; (2) CONFIRMATION — the signals you actually checked: position vs VWAP / opening range, 10-minute trend, relative strength vs SPY and the sector/peer ETF, and volume; (3) THESIS & RISK — the entry/exit logic, the level that would invalidate it, and the intended hold horizon; (4) WHY NOW — why act this cycle versus waiting. Be concrete and decision-grade; do not pad with generic phrasing.