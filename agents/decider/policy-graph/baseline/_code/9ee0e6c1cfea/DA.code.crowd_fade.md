---
id: DA.code.crowd_fade
version: code@9ee0e6c1cfea
agent: DeciderAgent
title: "🚫 CROWD-FADE AWARENESS"
node_type: code
polarity: caution
polarity_source: override
parent: DA.code
field: null
order: 1
owner: code
status: inactive
compiled: never
locked: true
provenance: decider_agent.py:ask_decision_agent
sep_before: ""
sep_after: ""
body_sha256: 36d4e0e971c34673876901da670beb9d063271e7141b7b0fd4431e9a0a67b263
tags: []
tickers: []
source_file: decider_agent.py
source_symbol: ask_decision_agent:contrarian_directive
code_sha: 9ee0e6c1cfea
condition: "'CROWD-FADE' not in user_prompt_template and 'CROWD-FADE' not in strategy_directives"
fires: false
position: user_template_tail
---

🚫 CROWD-FADE AWARENESS
- Be aware of herd behavior: when headlines are euphoric, consider taking profits; when panic dominates, look for entry opportunities.
- Avoid chasing names that are up big on stale/recycled news with no fresh catalyst. But if the macro thesis is strong and momentum confirms (volume, relative strength), buying into the trend is valid - not every strong move is a "crowd chase."
- Document your contrarian read in each reason when relevant (e.g., "Contrarian SELL into euphoria", "Buying strength - macro thesis intact, not a crowd chase").
- CRITICAL: Crowd-fade is a LENS, not a veto. It must NEVER prevent you from making BUY decisions when the data supports them. If you have cash, good setups, and the tape supports entry - BUY. Being contrarian does not mean sitting in cash while opportunities pass.