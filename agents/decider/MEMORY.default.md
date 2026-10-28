---
agent: DeciderAgent
purpose: Curated observations; current controls live in guidelines
last_updated: 2026-10-28
tags: [memory, decider, evidence, trading]
---

# Decider Agent — Memory

These are learning notes, not a second rulebook. The active guidelines and code-owned contracts determine actions and numeric thresholds. Historical versions, retired long-term rows and their original review tests remain preserved in the audit trail.

## Lessons Learned
- **#source-quality — Inspect the claim before the trade.** Prefer the supplied primary release, filing or dated event. Distinguish a company's own catalyst from peer sympathy, opinion and promotion. Coordinated or repeated coverage is a reason to inspect provenance, not proof that a price move is fraudulent.
- **#confirmation — Unknown micro-data is not failed confirmation.** Intraday VWAP, 10-minute/1-hour trend and relative volume are often absent. Use available multi-day structure, current price, relative strength and supplied catalyst evidence. Do not invent a metric or let missing optional data silently veto a valid setup.
- **#regime — Separate the market backdrop from the candidate.** Falling or volatile markets can contain opportunities. The regime and macro rules govern size and scrutiny; the candidate must still pass its own setup, stop and account controls.
- **#priced-kill — Record an executable price.** A narrative such as “exit on a 20-day break” was associated with historical loss tails. Current policy requires a numeric entry kill and controls its distance. That association is not proof that tighter stops always improve returns.
- **#churn — Preserve entry provenance.** The July 1 INTC/LRCX note described recent system entries being mistaken for synced inventory. Check ownership and entry source; ordinary short-term noise is not the same as a broken thesis. Binding exits still take priority.
- **#earnings — Separate the strategy from the calendar.** Standard entries avoid their own earnings inside the hold window. An intentional earnings_event entry needs verified timing and its own capped budget; the entire stake remains exposed to a gap. Post-release opportunities require results and the price response, not merely a familiar company name.

## Patterns to Watch
- Controlled pullbacks, oversold reversals and new price-confirmed catalysts are candidate families, not guaranteed winners. Compare outcomes within regime and time period; examples selected after a move are not a complete opportunity denominator.
- Crowded narratives can unwind, but a stock near highs is not automatically a pump and a falling price is not automatically cheap. Keep the active anti-chase controls and judge the specific evidence.

## Mistakes to Avoid
- **#unexecutable-gate — Requiring an entry quote that the input never supplies previously locked the book in cash.** Use the current supplied price as the entry reference and derive only what valid supplied numbers support.
- Do not turn a macro event into an unreviewed blanket liquidation rule, mix older stop thresholds into the active policy, or repeat a historical falsifier as a live trading instruction.
