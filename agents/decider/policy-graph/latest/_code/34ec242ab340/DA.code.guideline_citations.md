---
id: DA.code.guideline_citations
version: code@34ec242ab340
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
body_sha256: b0d53a12b9d4b70efb24009ee2864cd8692a5d07f22a0f6e4fbf9d8044151b0a
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: "ask_decision_agent:prompt+=#8"
code_sha: 34ec242ab340
condition: null
fires: true
position: user_prompt_tail
---


GUIDELINE CITATIONS (policy graph — REQUIRED on every decision): Every decision MUST carry one extra key "cited": a list of 1 to 4 guideline ids taken from the GUIDELINE INDEX below — first the gate that decided it (the rule you applied), then the lesson you weighed or the code policy you followed. Ids also appear as ⟨id⟩ after each guideline in your system prompt, with its record (how often it was cited in the last 7/30/90 days and the win rate of the trades it drove — weigh a rule by that record, not by its wording). Cite ids exactly as printed; never invent one. A decision without "cited" is incomplete: the ids are stored with the reason so every guideline's realized win rate can be measured on the Policy Graph tab.