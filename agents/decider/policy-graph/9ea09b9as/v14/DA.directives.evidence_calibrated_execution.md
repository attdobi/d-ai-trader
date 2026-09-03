---
id: DA.directives.evidence_calibrated_execution
version: DeciderAgent.9ea09b9as.v14
agent: DeciderAgent
title: "Evidence-Calibrated Execution"
node_type: section
polarity: gate
polarity_source: heuristic
parent: DA.directives
field: strategy_directives
order: 2
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#581
sep_before: ""
sep_after: "\n\n"
body_sha256: 6121fd04cf2ba91e886d0870f2f3e1682520e5926514e6f00df4ed22a9cf9aea
tags: []
tickers: []
---
## Evidence-Calibrated Execution
The reviewed evidence covers 20 best and 20 worst closed trades, not the omitted mid-range trades. Use it to correct documented execution failures without claiming universal threshold superiority.

- Preserve the quick-harvest pullback playbook. The evidence includes realized pullback wins in DASH +4.1%, SHOP +3.4%, ADBE +3.4%, SNOW +2.6%, and RBLX +2.7%; do not reject an otherwise valid pullback merely because intraday micro-data is unavailable.
- Treat technical context as context, not a sufficient thesis. Positive monthly trend, RSI, and price above the 20d MA do not replace a current catalyst or valid pullback/reversal structure with relative-strength support.
- For technical pullbacks, use a half-size starter only when current data supports a constructive monthly trend, RSI roughly 52–62, price above/holding the 20d area, and sector/peer tape is not deteriorating. Do not average down a failed setup.
- Keep harvesting stale strength. The evidence includes realized gains after pullbacks became stale or lacked fresh confirmation: DASH +4.1%, ADBE +3.4%, SNOW +2.6%, and RBLX +2.7%. A fresh, price-confirmed catalyst can justify holding; otherwise bank a ≥+3% winner rather than treating an unrealized gain as permanent.