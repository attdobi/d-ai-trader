---
id: DA.code.guideline_citations
version: code@3674eb0468b4
agent: DeciderAgent
title: "GUIDELINE CITATIONS"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 15
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 2b787faa5fef840626571eb80e7edbf15296e1a52c104720caadc3b9068aa90b
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#8"
code_sha: 3674eb0468b4
condition: null
fires: true
position: user_prompt_tail
---


GUIDELINE CITATIONS (policy graph — record which guidelines drove each decision): Every decision MAY carry one extra key "cited": a list of up to 4 guideline ids taken from the GUIDELINE INDEX below — the rule you applied, the lesson you weighed, the code policy you followed. Cite ids exactly as printed; never invent one. The ids are stored with the reason so every guideline's realized win rate can be measured on the Policy Graph tab. Omit the key when no listed guideline applies.