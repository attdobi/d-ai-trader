---
id: FA.directives.current_process_biases_audit.declared_kill_audit
version: FeedbackAgent.9ea09b9as.v5
agent: FeedbackAgent
title: "DECLARED-KILL AUDIT"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 16
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#582
sep_before: ""
sep_after: ""
body_sha256: ad17c76d9be08a4fe6538a455b99f55760b79d83a6aee05cfb4ee21546a9aaa4
tags: []
tickers: []
---
13. DECLARED-KILL AUDIT: When a closed-trade row provides both a stated loss or kill criterion and a realized gain_pct, compare only those recorded values. If the closed loss is worse than the stated criterion, make setup-specific kill enforcement a candidate top adjustment. Summarizer must surface the declared kill criterion; Decider must honor that trade-specific criterion. Do not infer stop-order placement, intraday trigger timing, gaps, liquidity, or slippage unless supplied.