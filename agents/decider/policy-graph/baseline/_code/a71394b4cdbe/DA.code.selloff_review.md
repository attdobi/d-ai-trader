---
id: DA.code.selloff_review
version: code@a71394b4cdbe
agent: DeciderAgent
title: "Large selloff screen"
node_type: code
polarity: evidence
polarity_source: override
parent: DA.code
field: null
order: 7
owner: code
status: read-only
compiled: never
locked: true
provenance: policy_graph/selloffs.py:prompt_section
sep_before: ""
sep_after: ""
body_sha256: e6b4e6f3d4ab0a50acb80532a88cda3600439e6c37d3c664f2481cade1905d7f
tags: []
tickers: []
source_file: policy_graph/selloffs.py
source_symbol: prompt_section
code_sha: a71394b4cdbe
condition: "qualified selloff candidates in this cycle"
fires: true
position: user_prompt_dynamic
---
# LARGE SELLOFF REVIEW
Unheld names in the supplied momentum recap fell at least 8% from the prior close with observed price × session volume of at least $10,000,000. Include each ticker in considered with verdict buy, watch or reject, a concrete reason and cited rules. Put proposed BUYs in decisions as well. Verify reversal, risk limits and re-entry eligibility.