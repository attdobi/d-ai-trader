---
id: DA.directives.reminder
version: DeciderAgent.9ea09b9as.v10
agent: DeciderAgent
title: "Latest Feedback Reminder: Separate true alpha trades from synced inventory. Recent alpha-style pullback trades were roughly positive, while synced/inherited positions were a major expectancy leak. Synced losers such as COIN -5.2%, CMG -3.4%, LOW -3.9%, INTC -2.6%, WBD -1.3%, and CC -1.6% show that inherited positions without fresh confirmation should be quarantined, not rationalized. Rule: synced positions may only be held if catalyst is fresh, price is above VWAP, 10-minute trend is positive, RS is positive, and loss..."
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
provenance: prompt_versions#575
sep_before: ""
sep_after: ""
body_sha256: c3e83105982c95143584ca940deef95a2578b324c0670d550b66cd541749249e
tags: []
tickers: []
---
Latest Feedback Reminder: Separate true alpha trades from synced inventory. Recent alpha-style pullback trades were roughly positive, while synced/inherited positions were a major expectancy leak. Synced losers such as COIN -5.2%, CMG -3.4%, LOW -3.9%, INTC -2.6%, WBD -1.3%, and CC -1.6% show that inherited positions without fresh confirmation should be quarantined, not rationalized. Rule: synced positions may only be held if catalyst is fresh, price is above VWAP, 10-minute trend is positive, RS is positive, and loss...