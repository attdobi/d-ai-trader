---
agent: FeedbackAgent
purpose: Meta-lessons about the feedback process itself — what kinds of feedback actually changed behavior
last_updated: 2026-09-02
tags: [memory, feedback, meta, calibration]
graph_status: seed
---

# Feedback Agent — Memory

> Append-only knowledge log. Intended for future Obsidian graph view.
> **Conventions:**
> - Each entry starts with an ISO date (`## 2026-05-26`) and 1-3 `#tags`.
> - Use `[[wiki-links]]` to cross-reference tickers, themes, prior entries, or other agents.
> - Keep entries short (3-6 lines). One meta-lesson per entry.
> - Auto-appended by [[feedback_agent]] after each cycle; manually-added entries welcome.

## Feedback Calibration
*Which feedback styles produced measurable behavior change in the Decider/Summarizer agents next cycle.*
- Compact trigger → action → metric rules land. 3,000-character narratives were truncated to 500 characters mid-sentence and became the Decider's standing policy for weeks (v15–v19, Aug 2026).
- Computed numbers persuade; sampled anecdotes get argued away. The re-entry leak (−$156 over 18 trades) was visible only over the whole population.

## Anti-patterns in My Own Feedback
*Times I gave vague, narrative, or unmeasurable feedback. Avoid repeating.*
- Softening a measured rule because a critic objected ("do not restore a blanket two-session cutoff", Aug 27 / Sep 1 2026) while re-entries were the largest leak.
- Recommending gates on data the Decider never receives ("quoted entry reference", "documented support hold/reclaim") — the book sat in cash rejecting every candidate on 2026-09-02.
- Bundling 4–5 "major" changes per candidate, so no realized delta could be attributed.

## Cross-Agent Observations
*Patterns spanning Summarizer → Decider that no single agent could see alone.*
- News was not the source of edge Jul–Sep 2026: nearly every BUY was a screener technical pullback; the Summarizer's 33-field evidence card was never consumed by the Decider (only headlines + insights are). Summarizer leverage = regime/sector/extension context.

---

## Log

<!--
Template for new entries:

## YYYY-MM-DD #meta-pattern
- **What I told the Decider/Summarizer:** (1 line, quoted)
- **What actually changed next cycle:** (measurable outcome)
- **Lesson for next feedback round:** (specific adjustment)
- **Related:** [[prior-feedback-entry]]
-->

## 2026-09-02 #meta #trust-region #critic
- **What happened:** the critic rejected 6/6 candidates in the Aug 21 and Sep 1 batches at 0.90–0.95 confidence on "the rows do not validate"; the human overrode 6/6. I then treated the critic's objections as standing requirements and softened the re-entry quarantine — the rule with the largest measured effect.
- **Lesson:** a gate that fails everything is not a gate, and an objection must cite a contradiction, not a sample size. Cite the computed diagnostic and keep the rule; let the next review falsify it. **Related:** [[reentry-quarantine]]

## 2026-09-02 #meta #policy-persistence
- **What happened:** the weekly AUTO path replaced strategy_directives with a 500-char truncated reminder and blanked soul/memory. Human-approved Decider v14 lived 2 days, v18 lived 6 days; every realized-outcome measurement scored a policy that was no longer active.
- **Lesson:** before attributing an outcome to a shipped change, verify the change was still ACTIVE for the window. Fixed 2026-09-02 (reminder is appended; soul/memory carried forward).

## 2026-09-02 #meta #dead-prompt
- **What happened:** my evolved system_prompt / user_prompt_template were never executed by the weekly path — only the soul is injected. Three approved FeedbackAgent versions changed nothing but the soul.
- **Lesson:** verify the code path consumes a field before evolving it; put the lesson where it executes (soul, and the hardcoded weekly prompt).

## 2026-09-02 #meta #regime-confound
- **What happened:** all three measured realized_winrate_delta values (−0.25, −0.21, −0.25) were negative, including the change the critic and human both approved — the window was a momentum unwind.
- **Lesson:** realized deltas are regime-confounded; compare against the regime split before blaming a change. **Related:** [[regime]]
