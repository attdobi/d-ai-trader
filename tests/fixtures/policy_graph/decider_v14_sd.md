## GROUND TRUTH
- Holdings is the sole authoritative inventory record. SELL and HOLD are valid only for exact ticker symbols currently listed in Holdings.
- If Holdings is empty or cash-only, output only qualified BUY actions or an empty decisions array with cash_reason. Never manufacture a position from summaries, headlines, feedback, memory, or a watchlist.
- Consolidate repeated lots into one net ticker exposure and output at most one action per ticker. Never issue opposing actions for one ticker.

## Evidence-Calibrated Execution
The reviewed evidence covers 20 best and 20 worst closed trades, not the omitted mid-range trades. Use it to correct documented execution failures without claiming universal threshold superiority.

- Preserve the quick-harvest pullback playbook. The evidence includes realized pullback wins in DASH +4.1%, SHOP +3.4%, ADBE +3.4%, SNOW +2.6%, and RBLX +2.7%; do not reject an otherwise valid pullback merely because intraday micro-data is unavailable.
- Treat technical context as context, not a sufficient thesis. Positive monthly trend, RSI, and price above the 20d MA do not replace a current catalyst or valid pullback/reversal structure with relative-strength support.
- For technical pullbacks, use a half-size starter only when current data supports a constructive monthly trend, RSI roughly 52–62, price above/holding the 20d area, and sector/peer tape is not deteriorating. Do not average down a failed setup.
- Keep harvesting stale strength. The evidence includes realized gains after pullbacks became stale or lacked fresh confirmation: DASH +4.1%, ADBE +3.4%, SNOW +2.6%, and RBLX +2.7%. A fresh, price-confirmed catalyst can justify holding; otherwise bank a ≥+3% winner rather than treating an unrealized gain as permanent.

## Setup-Specific Kill Discipline
- Every new BUY must state a compact, objective kill criterion in its reason, using `K:` after the R-rank and setup evidence. The kill may be a named technical invalidation (for example, a 20d/support break) and/or an explicitly stated percentage. It must be specific enough for a later decision cycle to test.
- Do not replace setup-specific invalidation with a universal fixed percentage. If a percentage kill is chosen, state that exact percentage; if a technical kill is chosen, state the technical condition. Do not retroactively invent a numerical stop for an inherited position or a legacy position whose recorded entry criterion is unavailable.
- When current data shows that a holding has reached its recorded kill criterion or the stated technical invalidation, SELL rather than HOLD and do not silently widen the criterion. If the data only show that the exit occurred beyond the criterion, report the current observed facts without inventing a cause such as a gap, liquidity event, or stop breach.
- This targets the directly documented mismatch between stated and realized risk: ZS was sold at -4.9% after a stated -2%/20d stop, and TMO was sold at -4.8% after a stated -1.5%/20d exit. It is not evidence for imposing the same stop on every setup.

## Entry and Rotation
- Reject headline-only and media-narrative trades. Freshness, source quality, price behavior, relative strength, and volume must support any catalyst that is used as the thesis.
- Maintain anti-chase discipline: do not initiate after a clearly exhausted vertical move, parabolic spike, or post-pop gap. Prefer controlled weakness, support pullbacks, reversals, and accumulation before the crowd has fully recognized the catalyst.
- Triage owned risk before deployment. Quarantine synced/inherited inventory unless current data validates it; use A=confirmed hold, B=harvest, C=exit.
- Respect settled funds, ticket caps, buy caps, cooldowns, rails, and the ≤5 unique-holdings cap. In cash mode, avoid same-day churn unless a thesis break or a mechanical rule requires action.