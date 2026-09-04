---
id: DA.runtime.inputs
version: DeciderAgent.9ea09b9as.v26
agent: DeciderAgent
title: "Per-cycle runtime inputs"
node_type: data
polarity: structure
polarity_source: override
parent: DA.root
field: null
order: 0
owner: runtime
status: generated
compiled: never
locked: true
provenance: generated
sep_before: ""
sep_after: ""
body_sha256: a43536a1d057af19b0ac3ea5fcf2d890ffe01bf1224b4701efa43f51aeae4263
tags: []
tickers: []
---
Per-cycle data blocks — not policy text; varies per cycle.

Placeholders filled by safe_format_template from the user prompt template:
- {account_mode}
- {settled_cash}
- {today_tickets_used}
- {daily_ticket_cap}
- {today_buys_used}
- {daily_buy_cap}
- {minutes_since_last_entry}
- {tickers_entered_today}
- {min_buy}
- {typical_buy_low}
- {typical_buy_high}
- {max_buy}
- {index_regime}
- {holdings}
- {summaries}
- {momentum_recap}
- {feedback_context}
- {settled_cash_value}
- {min_buy_amount}

Blocks supplied by decider_agent.ask_decision_agent every cycle:
- Holdings with K:/D: kill prices (RunContext / Schwab sync)
- INDEX REGIME line (contrarian_screener.format_index_regime)
- CONTRARIAN WATCHLIST rows (contrarian_screener.format_contrarian_watchlist)
- QUARANTINE tickers (recently exited names)
- # LESSONS rows (decider_memory.format_long_term_memory, weight/recency ranked)
- # RECENT ACTIVITY (decider_memory.build_working_memory)
- Feedback Snapshot (latest feedback row)

# Auto-context lines appended for placeholders the template does not declare: {available_cash}