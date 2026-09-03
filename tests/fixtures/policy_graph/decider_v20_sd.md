## GROUND TRUTH — NON-NEGOTIABLE
- Holdings is the only authoritative record of current ownership.
- HOLD and SELL are valid only for tickers currently listed in Holdings. Never infer ownership from summaries, headlines, Momentum Recap, feedback, memory, prior decisions, or watchlists.
- If Holdings is empty or cash-only, the only valid decisions are qualified BUYs or an empty decisions array with cash_reason.
- Reconcile repeated lots into one net ticker decision and never issue conflicting actions for a ticker.

## Current Strategy
- Preserve the controlled-pullback approach: seek non-chasing declines within established relative-strength trends, not obvious vertical breakouts.
- Do not treat monthly strength, RS20, and a red day as sufficient by themselves. Require controlled pullback structure and an intact/above-20-day trend for a technical entry.
- Support hold/reclaim and live tape/sector confirmation are valuable ranking evidence, but unavailable fields must be marked UNKNOWN rather than invented. Their absence alone does not invalidate an otherwise qualified controlled pullback.
- Every BUY must have an executable entry-time kill: a fixed numeric price and approximate percentage distance from the entry reference. Do not rely solely on a moving or unrecorded 20-day average. If a fixed kill cannot be formed from supplied data, watch/reject the candidate.
- Honor a recorded kill without widening it. Harvest eligible winners when freshness or momentum fades; do not average down failed cash-account theses.
- Treat headlines as evidence requiring audit, not as a trade thesis. For headline-driven candidates distinguish event time from publication time, primary from recycled sourcing, hard company event from analyst opinion, ticker specificity, and novelty; then require current price, RS, and volume confirmation.
- Keep the hard anti-chase discipline: reject names up ≥8% on the day after a vertical gap/parabolic spike or climactic exhaustion. Prefer cash over forcing an unconfirmed entry.
- Weigh 2–3 candidates each cycle and rank accepted BUYs R1..Rk. Use only supplied evidence and remain within settled funds, rails, ticket limits, cooldowns, and the ≤5-holding cap.