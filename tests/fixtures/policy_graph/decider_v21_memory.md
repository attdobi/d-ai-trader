---
agent: DeciderAgent
purpose: Trade-by-trade lessons, recurring mistakes, and pattern recognitions
last_updated: 2026-09-02
tags: [memory, decider, trading, risk-management]
graph_status: seed
---

# Decider Agent — Memory

> Append-only knowledge log. Intended for future Obsidian graph view.
> **Conventions:**
> - Each entry starts with an ISO date (`## 2026-05-26`) and 1-3 `#tags`.
> - Use `[[wiki-links]]` to cross-reference tickers, themes, prior entries, or other agents.
> - Keep entries short (3-6 lines). Specific > general. One lesson per entry.
> - Auto-appended by [[feedback_agent]] after each cycle; manually-added entries welcome.

## Lessons Learned
*High-confidence rules earned through P&L.*
- **#gap-chase — Never buy a vertical pop.** Do not initiate a BUY in a name already up ≥10% on the day, or extended near its highs right after a gap/spike — you become exit liquidity and continuation is unlikely. **Front-run instead:** buy weakness, pullbacks, and bases BEFORE the obvious catalyst. Markets are manipulated; the obvious breakout is bait. (Paid for by [[IRDM]] 2026-06-29.)
- **#extension-chase — The swing-timeframe chase is extension above the 20d MA.** ≤5% full size; 5–8% half size and only in RISK-ON; >8% reject. A red day in a name 12% above its 20d MA is an unwind's first leg, not a pullback into support. (Paid for by [[IONQ]] −10.4%, [[RKLB]] −7.2%, [[MRVL]] −9.1%, [[ORCL]] −5.0%, Aug 2026.)
- **#regime — Read the INDEX REGIME line before any BUY.** RISK-ON: full rails. MIXED: max 2 new BUYs at half size. RISK-OFF: cash is the default; max 1 half-size BUY in an oversold reversal or a name ≤3% above its 20d MA, harvest at +2%.
- **#priced-kill — A kill is a price.** Write `K:<price>;D:<%>` on every BUY from supplied numbers (higher of 20d MA / stated support and entry × 0.97). No priced kill within 6% = pass. Binding on the first breach.
- **#reentry-quarantine — No re-entry within 2 sessions of an exit.** After a losing exit, also require a reclaim of the failed level or a new catalyst. (18 re-entries within 3 days: 33% win, −$156; spaced entries: 53% win, +$145. Jul–Sep 2026.)
- **Consider 2–3 of the best setups each cycle**, ranked R1..Rk — not a single name.

## Patterns to Watch
*Setups that historically worked, with the conditions that defined "worked."*
- **Controlled pullback ≤5% above the 20d MA, RS20 > 0, 1mo +8..+20%, RSI 48–62, in RISK-ON** — [[NET]] +8.9%, [[V]] +5.0%, [[SCHW]] +4.8%, [[CRM]] +4.5%, [[CVNA]] +5.5%, [[SNAP]] +3.9% (Jul–Aug 2026). Works while the leaders are above their 20d MAs.

## Mistakes to Avoid
*Tagged by failure mode: `#stop-too-tight`, `#held-too-long`, `#narrative-trap`, `#gap-chase`, `#extension-chase`, `#reentry`, `#size-too-big`, etc.*
- **#unexecutable-gate** — requiring a "quoted entry reference" that nothing supplies locked the book in cash (2026-09-02). The watchlist prints price, 20d MA and the 3% kill: use them.

---

## Log

<!--
Template for new entries:

## YYYY-MM-DD #ticker-XYZ #failure-mode
- **Setup:** thesis on entry (1-2 sentences)
- **Outcome:** +X.X% over N days OR -X.X% / stopped
- **Root cause:** what the data said vs what I did
- **Adjustment:** specific rule change for next time
- **Related:** [[prior-similar-trade]] or [[shared-pattern]]
-->

## 2026-06-29 #IRDM #gap-chase #exit-liquidity
- **Setup:** Bought IRDM ~$53–54 AFTER a +22% pre-market pop (SpaceX-IPO sympathy), extended near highs, vol 2.3×. The buy reason literally read "+22% … near hi."
- **Outcome:** Immediately underwater — textbook top-tick. The vertical move had already happened.
- **Root cause:** Chased strength / bought the breakout near highs = provided exit liquidity to whoever accumulated lower. Momentum-chasing, not contrarian.
- **Adjustment:** HARD anti-chase — never BUY a name already up ≥10% on the day or extended near highs after a gap/spike. Front-run the move (buy weakness/bases/pullbacks before the obvious catalyst), don't chase it. Evaluate 2–3 best setups per cycle. **Related:** [[front-run-not-chase]]

## 2026-09-02 #regime #extension-chase #reentry #kill-geometry
- **Setup:** Aug 5–14 the "controlled pullback in a strong monthly trend" playbook ran 65–73% win / +$339 while SPY/QQQ and the momentum leaders were above their 20d MAs. Aug 17 – Sep 2 the SAME rules ran 22–33% win / −$275: every extension bucket lost, the 6–10%-above-20d bucket went 0-for-5.
- **Outcome:** [[IONQ]] −10.4% (entered +15% above 20d), [[RKLB]] −7.2% (+9.4%), [[MRVL]] −9.1% (+9.0%), [[ORCL]] −5.0%/−3.9%/−3.2% (three re-entries in 8 days), [[MDB]] −15.2% (earnings gap through an unpriced "20d break" kill).
- **Root cause:** (1) the screener capped only the DAY move, so "pullbacks" 9–18% above the 20d MA were served as front-run candidates; (2) the only kill was "exit on 20d break" — 9–15% away; (3) same-ticker re-entry within 3 days of an exit (18 trades, −$156) was the largest single leak; (4) no regime read — the prompt said cash is failure, so the book stayed deployed into a momentum unwind.
- **Adjustment:** INDEX REGIME gate; extension cap ≤5% full / 5–8% half (RISK-ON only) / >8% reject; `K:<price>;D:<%>` from supplied numbers, ≤3% or half size, ≤6% or pass; 2-session re-entry quarantine (screener drops exited names); max 2 correlated semis/AI/quantum names.
- **Related:** [[front-run-not-chase]] [[feedback_agent]] [[reentry-quarantine]]

## 2026-09-01 #kill-geometry #risk-management
- [[IONQ]] lost -10.4% after an entry 15% above its 20-day level with only an "exit on 20d break" condition.
- [[LRCX]] lost -3.0% after its declared <$310 kill was breached at $304.24.
- **Adjustment:** record a fixed numeric kill and entry-to-kill distance at entry; never treat a moving or unrecorded average as a complete kill plan.

## 2026-09-01 #technical-pullback #evidence-calibration
- [[TEAM]] +37.1%, [[SMCI]] +7.1%, and [[NET]] +8.9% were profitable technical-dip entries despite sparse supplied live support/tape fields.
- **Adjustment:** keep controlled pullback, positive RS20, and intact-trend requirements, but mark absent support/tape as UNKNOWN and use it for ranking rather than automatically rejecting the setup.