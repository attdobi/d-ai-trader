## GROUND TRUTH — NON-NEGOTIABLE
- Holdings is the only authoritative record of current ownership.
- HOLD and SELL are valid only for tickers currently listed in Holdings. Never infer ownership from summaries, headlines, Momentum Recap, feedback, memory, prior decisions, or watchlists.
- If Holdings is empty or cash-only, the only valid decisions are qualified BUYs or an empty decisions array with cash_reason.
- Reconcile repeated lots into one net ticker decision and never issue conflicting actions for a ticker.

## Current Strategy (2026-09-02 — regime-gated controlled pullbacks with priced kills)
Evidence, computed over all 79 campaigns closed Jul 1 – Sep 2, 2026 (not a sample): the controlled-pullback playbook ran 54% win / +$125 on RISK-ON entries and 45% / −$64 on RISK-OFF entries; losers whose only kill was "exit on 20d break" cost −$523 over 28 trades (average loser −4.3%) against an average loser of −2.8% with a numeric kill; same-ticker re-entries within 3 days ran 33% win / −$118 against 54% / +$179 for spaced entries; entries more than 5% above the 20d MA outside RISK-ON ran 33% / −$58. The breakeven win rate at the current payoff (avg win +4.6%, avg loss −3.8%) is ~46%.

1. REGIME GATE — first, every cycle. RISK-ON = up to 3 new BUYs, full rails. MIXED = ≤2 new BUYs at half size, extension ≤5%. RISK-OFF = cash default, ≤1 half-size BUY (oversold reversal or ≤3% above the 20d MA), harvest at +2%. Falsified if 20 RISK-OFF entries taken under this gate average worse than −1%.
2. EXTENSION CAP — ≤5% above the 20d MA at full size; 5–8% at half size in RISK-ON only; >8% reject as a chase. Falsified if 20 rejected >8% names would have averaged better than +1.5% over the next 3 sessions.
3. PRICED KILL — every BUY ends with K:<price>;D:<%>, K = the higher of (20d MA level or stated support, current price × 0.97). D ≤3% full size, ≤6% half size, >6% pass. K is binding on the first breach; a holding without a K price uses cost × 0.97. Falsified if the average loser under priced kills exceeds −3.5% over 20 losers.
4. RE-ENTRY QUARANTINE — no BUY within 2 sessions of exiting the same ticker (QUARANTINE line + RECENT ACTIVITY); after a losing exit also require a reclaim of the failed level or a genuinely new catalyst. Falsified if 15 quarantined names would have averaged better than +1% over the next 3 sessions.
5. CORRELATION — semis / AI-infrastructure / quantum / space are one book: at most 2 at once, shared risk budget.
6. HARVEST — ≥ +3% (≥ +2% in RISK-OFF) is a default sell unless a fresh ≤1-session catalyst is still price-confirmed in RISK-ON. With winners capped near +3–5%, the stop distance is the lever, not the harvest.
7. Keep the day-timeframe anti-chase (≥8% day / gap / parabolic = reject), the headline audit (event time vs article time, primary vs recycled, hard event vs analyst opinion, ticker-specific vs indirect), and the intraday-signal allowance (missing VWAP/10m/1h never disqualifies a qualified setup).
8. Weigh 2–3 candidates each cycle, rank accepted BUYs R1..Rk, use only supplied evidence, and stay within settled funds, rails, ticket limits, cooldowns and the ≤5-holding cap.