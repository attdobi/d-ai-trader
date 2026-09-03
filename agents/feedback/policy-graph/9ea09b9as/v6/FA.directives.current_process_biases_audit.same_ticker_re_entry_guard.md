---
id: FA.directives.current_process_biases_audit.same_ticker_re_entry_guard
version: FeedbackAgent.9ea09b9as.v6
agent: FeedbackAgent
title: "SAME-TICKER RE-ENTRY GUARD"
node_type: rule
polarity: gate
polarity_source: heuristic
parent: FA.directives.current_process_biases_audit
field: strategy_directives
order: 17
owner: db
status: inert
compiled: stored
locked: false
provenance: prompt_versions#593
sep_before: ""
sep_after: ""
body_sha256: 901e76de9676f57823730125a9d99e33c172a62ae3d70adc29e2174b431e88d4
tags: []
tickers: []
---
14. SAME-TICKER RE-ENTRY GUARD: When a ticker has a documented prior exit, Summarizer must surface that exit date/outcome and label post-exit new-catalyst and support-reset confirmation as present, absent, or unknown. Decider should block a new same-ticker BUY for two full trading sessions after an exit unless a genuinely new post-exit catalyst or a retest-and-reclaim of defined support is documented. Do not infer re-entry, independent lots, or these fields from repeated ticker rows alone.