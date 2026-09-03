---
id: DA.ltm.21
version: ltm@3618194f4926
agent: DeciderAgent
title: "RE-ENTRY QUARANTINE: never BUY a ticker on the QUARANTINE line or one…"
node_type: ltm
polarity: evidence
polarity_source: override
parent: DA.ltm
field: null
order: 1
owner: decider_memory
status: active
compiled: never
locked: true
provenance: decider_memory#21
sep_before: ""
sep_after: ""
body_sha256: 5a1212973e4c4c46ed8234f17f9f63db7c6a2830eda4716b825f34151d7357b1
tags: [reentry, churn]
tickers: []
kind: rule
source: human
weight: 2.0
ticker: null
row_created_at: 2026-09-02T14:57:20.876634
row_updated_at: 2026-09-02T14:57:20.876634
injected: true
active: true
---
- [rule] RE-ENTRY QUARANTINE: never BUY a ticker on the QUARANTINE line or one exited within the last 2 sessions; after a losing exit also require a reclaim of the failed level or a genuinely new catalyst. Same-ticker re-entries within 3 days ran 33% win / -$156 vs 53% / +$145 for spaced entries (Jul-Sep 2026).