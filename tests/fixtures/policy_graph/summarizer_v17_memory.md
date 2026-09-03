---
agent: SummarizerAgent
purpose: Distilled lessons from market-summary extraction cycles
last_updated: 2026-09-02
tags: [memory, summarizer, market-signal, media-watch]
graph_status: seed
---

# Summarizer Agent — Memory

> Append-only knowledge log. Intended for future Obsidian graph view.
> **Conventions:**
> - Each entry starts with an ISO date (`## 2026-05-26`) and 1-3 `#tags`.
> - Use `[[wiki-links]]` to cross-reference tickers, themes, prior entries, or other agents.
> - Keep entries short (3-6 lines). Specific > general. One lesson per entry.
> - Auto-appended by [[feedback_agent]] after each cycle; manually-added entries welcome.

## Source Quality Notes
*Per-source reliability scores will accumulate here.*

## Extraction Patterns
*Recurring catalyst shapes and their hit-rate will accumulate here.*
- Only the 3 headlines and the insights paragraph reach the Decider. Anything that matters must be IN the insights paragraph — regime read first, then sector direction, then extension/crowding flags on headlined names, then catalysts.

## Media-Manipulation Watch
*Patterns of coordinated coverage that historically preceded reversals.*
*See also: [[shared/media-narrative-playbook]] (TBD).*
- Momentum-leader coverage peaks near the end of the run: IONQ / RKLB / quantum-space and AI-infrastructure headlines were densest Aug 12–18, 2026, right before the cohort unwound 7–15%. Dense, synchronized "leader" coverage on a day the cohort is red = crowding flag.

---

## Log

<!--
Template for new entries:

## YYYY-MM-DD #tag1 #tag2
- **Observation:** what happened (cite [[ticker]] or [[event]])
- **Lesson:** what to do differently next time
- **Confidence:** low | medium | high
- **Related:** [[other-entry]] or [[ticker]]
-->

## 2026-09-02 #pipeline #dead-field
- **Observation:** the 33-field catalyst_validity evidence card evolved through v5–v16 was never consumed — the Decider parses only `headlines` and `insights`; the company-extraction step reads the same two.
- **Lesson:** keep the card compact; spend the tokens on the insights paragraph the Decider actually reads.
- **Confidence:** high (verified in decider_agent.py)

## 2026-09-02 #edge #regime-context
- **Observation:** Jul–Sep 2026 nearly every BUY was a screener technical pullback; news-driven entries ([[AMZN]] Evercore call −1.9%, [[CVX]] oil route −1.3%) underperformed. The losses came from a momentum unwind (Aug 17 – Sep 2) that no summary flagged — SPY held its 20d MA while the leaders fell 5–15%.
- **Lesson:** the Summarizer's leverage is CONTEXT the screener cannot see: index and leader regime, sector-ETF direction, crowding/extension of headlined names, scheduled events (earnings — [[MDB]] −15.2% gapped through an earnings print), coordinated coverage. Say "leaders rolling over" when the tape shows it.
- **Confidence:** high
- **Related:** [[feedback_agent]] [[regime]]

## 2026-09-01 #catalyst-provenance #analyst-opinion
- **Observation:** [[AMZN]] entered on a fresh Evercore AI call after an initial +3.7% move, but reported 0.9x volume and closed at -1.9%.
- **Lesson:** Record the underlying event time and classify analyst opinion separately from a hard corporate event; article recency alone is not validation.
- **Confidence:** medium
- **Related:** [[AMZN]] [[shared/media-narrative-playbook]]