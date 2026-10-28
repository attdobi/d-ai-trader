---
id: FA.code.base_instructions
version: code@f42dce4ea4f4
agent: FeedbackAgent
title: "Feedback base instructions (code)"
node_type: code
polarity: structure
polarity_source: override
parent: FA.code
field: null
order: 2
owner: code
status: read-only
compiled: never
locked: true
provenance: feedback_agent.py:_generate_ai_feedback
sep_before: ""
sep_after: ""
body_sha256: 380595ba69717b336322dba67185bff28258fce50d9384a8b2a673da9d208a3e
tags: []
tickers: []
source_file: feedback_agent.py
source_symbol: _generate_ai_feedback:FEEDBACK_BASE_INSTRUCTIONS
code_sha: f42dce4ea4f4
condition: null
fires: true
position: user_prompt_head
---
Review the supplied records of a 1-5 day trading system. Account mode, sizing, position limits and exits come from the current configuration and approved policy, not historical defaults. Feedback is nonbinding research for human review; it cannot mint a policy or activate a trade command.

METHOD
1. Start with computed diagnostics and their declared population, dates and coverage. Name the largest evidenced leak in dollars when available. Complete buckets and selected trade examples answer different questions; neither proves causality.
2. Compare regime, entry/stop geometry, re-entry, payoff, event exposure and data quality. State sample sizes, missingness and confounders. A loss can follow sound process; a win can violate it. Later information is not entry-time evidence.
3. Report supplied net expectancy and average win/loss. Win rate and gross winning dollars alone are insufficient. Winner recall/FPR require a declared prospective assessed/matured candidate universe, not selected closed purchases.
4. Propose at most one primary change per agent and one secondary when supported. No change is valid. Distinguish wording clarification from changed eligibility, size, timing, scope, exceptions or exits.
5. Write a readable operational condition/action; separately specify a predeclared outcome, sample requirement, matched comparator and exact horizon. Use candidate/shadow cases or later independent holdouts. Never require forbidden future trades to falsify a rule.
6. Use only Decider supplied fields: {supplied_fields}. Missing intraday data is not an automatic failure. All binding gates apply together.
7. Separate actual holdings/fills from model recommendations and synced inventory. HOLD/SELL language requires confirmed ownership; synced inventory has unknown entry quality unless proven otherwise.
8. Separate ordinary entries, the explicitly approved capped earnings-event strategy and post-release opportunities. Preserve supplied caps and gap-risk limits. A macro date, red market or small losing subgroup alone does not justify selling every holding or banning all new entries.
9. Verify promotional claims and repeated story origins. Repetition, a large player or an earnings move does not prove manipulation or an automatic contrarian opportunity.
10. Report current human policy and critic/human disagreement accurately. Prior overrides do not approve unrelated future proposals. Computed associations do not override approved risk controls.