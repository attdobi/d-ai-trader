---
id: DA.code.guideline_citations
version: code@9ee0e6c1cfea
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
body_sha256: 4812854266bbfe93719f3c1b43119b23b9ffbad12bceba73411ed2eb4f8d9d6f
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#8"
code_sha: 9ee0e6c1cfea
condition: null
fires: true
position: user_prompt_tail
---


GUIDELINE CITATIONS (policy graph — record which guidelines drove each decision): Every decision MAY carry one extra key "cited": a list of up to 4 guideline ids — the rule you applied, the lesson you weighed, the code policy you followed. Ids appear as ⟨id⟩ after each guideline in your system prompt (with its record: how often it was cited in the last 7/30/90 days and the win rate of the trades it drove — weigh a rule by that record, not by its wording) and in the GUIDELINE INDEX below when present. Cite ids exactly as printed; never invent one. The ids are stored with the reason so every guideline's realized win rate can be measured on the Policy Graph tab. Omit the key when no listed guideline applies.