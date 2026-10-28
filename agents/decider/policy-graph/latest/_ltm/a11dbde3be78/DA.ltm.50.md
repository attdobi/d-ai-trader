---
id: DA.ltm.50
version: ltm@a11dbde3be78
agent: DeciderAgent
title: "Requiring a separately quoted entry reference that the inputs never s…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 22
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#50
sep_before: ""
sep_after: ""
body_sha256: 6247e8841a5ff82289d150948208d316aabf8c075364e1a235a5a066fb75b9ac
tags: [unexecutable-gate, confirmation]
tickers: []
kind: mistake
source: operator_audit
weight: 1.3
ticker: null
row_created_at: 2026-10-28T14:45:32.204916
row_updated_at: 2026-10-28T14:45:32.204916
injected: true
active: true
---
- [mistake] Requiring a separately quoted entry reference that the inputs never supply can lock the book in cash. Use the current supplied price and valid supplied support/20-day-MA numbers under the active priced-kill rule; do not fabricate levels.