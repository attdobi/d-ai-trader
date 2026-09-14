---
id: DA.runtime.inputs
version: DeciderAgent.baseline.v0
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
body_sha256: b14072af712dd5ec0efc403cdf27ce3a8fa3f6f9fde1e90e308c59dd96092930
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
- EVENT CALENDAR block (event_calendar.format_event_calendar: today's date, sessions to the next FOMC / CPI / jobs report, earnings dates of holdings and watchlist names, event-risk score)
- QUARANTINE tickers (recently exited names)
- # LESSONS rows (decider_memory.format_long_term_memory, weight/recency ranked)
- # RECENT ACTIVITY (decider_memory.build_working_memory)
- Feedback Snapshot (latest feedback row)

# Auto-context lines appended for placeholders the template does not declare: {index_regime}, {available_cash}