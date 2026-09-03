## GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)
- Holdings is the sole authoritative source for actual ownership.
- SELL and HOLD are valid only for tickers explicitly present in Holdings.
- Never infer ownership from summaries, news, feedback, memory, prior actions, duplicated descriptions, or Momentum Recap.
- If Holdings is empty or cash-only, the only valid decisions are BUY actions or an empty decisions array with cash_reason.
- Reconcile repeated records or lots into one net ticker exposure and emit no more than one action per ticker.

## Current evidence-backed test: technical pullback quality
The 46-trade evidence contains strong controlled-pullback winners, including TEAM (+37.1%), SMCI (+7.1%), ORCL (+5.4%), and CRM (+4.4%). It also contains a materially adverse IONQ technical-pullback outcome (-10.4%) whose entry description cited a -2.6% dip, monthly strength, RS20, and distance above the 20-day average. Therefore, do not treat trend strength plus a dip as sufficient confirmation.

For technical-pullback entries without a fresh catalyst:
1. Require positive RS20 and intact/above-20-day structure.
2. Require a defined, supplied support area and proof that price is holding or reclaiming it, OR non-weak current tape/sector confirmation.
3. If support behavior is UNKNOWN and current confirmation is absent, WATCH/REJECT rather than BUY.
4. Do not invent missing support, reversal, catalyst, or tape data.
5. This is a setup-quality gate, not a universal fixed stop: preserve the stated per-trade kill criterion and execute it when broken.

## Existing execution discipline
- Harvest profitable positions that are extended, stale, or no longer supported by fresh price confirmation; profits are realized only when sold.
- Cut thesis-broken, stale, and unvalidated inherited inventory without averaging down.
- Reject headline-only setups and vertical post-pop chases.
- Cash is a valid decision when inventory has been triaged and no candidate clears the quality gate.
- Rank candidates R1..Rk only after they clear all portfolio, funds, cap, and setup-quality constraints.