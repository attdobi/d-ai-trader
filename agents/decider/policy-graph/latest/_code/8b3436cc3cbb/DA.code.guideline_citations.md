---
id: DA.code.guideline_citations
version: code@8b3436cc3cbb
agent: DeciderAgent
title: "GUIDELINE CITATIONS"
node_type: code
polarity: structure
polarity_source: override
parent: DA.code
field: null
order: 16
owner: code
status: read-only
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 150ac4ca89495cfa53daad2422399380a1856c6fc9e5e327a72bdeb035074507
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#8"
code_sha: 8b3436cc3cbb
condition: null
fires: true
position: user_prompt_tail
---


GUIDELINE CITATIONS (policy graph — REQUIRED on every decision): Every decision MUST carry one extra key "cited": a list of 1 to 4 guideline ids taken from the GUIDELINE INDEX below — first the gate that decided it (the rule you applied), then the lesson you weighed or the code policy you followed. Ids also appear as ⟨id⟩ after each guideline in your system prompt and after each LESSONS row (DA.ltm.<n>), with its record (how often it was cited in the last 7/30/90 days and the win rate of the trades it drove — weigh a rule by that record, not by its wording). Cite ids exactly as printed; never invent one. A decision without "cited" is incomplete: the ids are stored with the reason so every guideline's realized win rate can be measured on the Policy Graph tab.