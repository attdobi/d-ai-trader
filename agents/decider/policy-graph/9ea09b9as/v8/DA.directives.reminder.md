---
id: DA.directives.reminder
version: DeciderAgent.9ea09b9as.v8
agent: DeciderAgent
title: "Latest Feedback Reminder: Primary fix: stop defending weak confirmed-owned inventory before searching for new trades. The current sample has 20 trades, 25% win rate, average return -0.89%, 12 moderate losses, 4 breakevens, and 4 moderate profits. Average winner was about +3.7%, but average losing trade was about -2.6%, with NVDA -6.9% and -7.8% and USO -3.9% destroying expectancy. Rule: if buy_reasoning is Schwab synced position, classify as inherited inventory, never as a fresh entry. At first evaluation, hold..."
node_type: reminder
polarity: caution
polarity_source: override
parent: DA.directives
field: strategy_directives
order: 1
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#571
sep_before: ""
sep_after: ""
body_sha256: d47769738c855e596849247aab79cf47fb9e759fdb6dc610d143e8e255038308
tags: []
tickers: []
---
Latest Feedback Reminder: Primary fix: stop defending weak confirmed-owned inventory before searching for new trades. The current sample has 20 trades, 25% win rate, average return -0.89%, 12 moderate losses, 4 breakevens, and 4 moderate profits. Average winner was about +3.7%, but average losing trade was about -2.6%, with NVDA -6.9% and -7.8% and USO -3.9% destroying expectancy. Rule: if buy_reasoning is Schwab synced position, classify as inherited inventory, never as a fresh entry. At first evaluation, hold...