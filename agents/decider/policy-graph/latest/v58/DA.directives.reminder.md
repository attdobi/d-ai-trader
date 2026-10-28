---
id: DA.directives.reminder
version: DeciderAgent.9ea09b9as.v58
agent: DeciderAgent
title: "Latest Feedback Reminder (2026-10-22)"
node_type: reminder
polarity: caution
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 15
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#660
sep_before: ""
sep_after: ""
body_sha256: 136cea5637dd25d2ab070a394bcb69a12c2488fc5f887fb2747565237af9d202
tags: []
tickers: []
---
## Latest Feedback Reminder (2026-10-22)
- 1. LOSS CAP — IF a confirmed Holding shows P&L of -0.8% or worse THEN SELL. Otherwise next gate. Falsified if 20 triggered exits have a mean 5-session return above +1% from sale.
- 2. KILL BREACH — IF a confirmed Holding is $0.01 or more below its K: price THEN SELL. Otherwise next gate. Falsified if 20 exits have a mean 5-session return above +1% from sale.
- 3. EVENT — IF EVENT CALENDAR for a new BUY shows MACRO WINDOW flag 1 THEN pass. Otherwise next gate. Falsified if 20 passed rows tracked as shadow trades average above +1% over 5 sessions.

Do NOT place too much weight on "RISK-OFF ..." because this is preventing great trading opportunities. The last few days have seen no trades dispite gains in the market. Learn from this! High risk can become high reward, especially when the markets are dipping or nearing a local / daily minima.