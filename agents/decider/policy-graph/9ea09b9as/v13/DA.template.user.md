---
id: DA.template.user
version: DeciderAgent.9ea09b9as.v13
agent: DeciderAgent
title: "User prompt template"
node_type: template
polarity: structure
polarity_source: override
parent: DA.root
field: user_prompt_template
order: 0
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#580
sep_before: ""
sep_after: ""
body_sha256: 134351491acf722a2f475fd7dbbdecd867e93d2cff757682d7b137b206a79292
tags: []
tickers: []
---
ACCOUNT
- Mode: {account_mode}
- Settled Funds (USD): ${settled_cash}

DAILY STATE
- Today tickets used / cap: {today_tickets_used}/{daily_ticket_cap}
- Today buys used / cap: {today_buys_used}/{daily_buy_cap}
- Minutes since last new entry: {minutes_since_last_entry}
- Tickers entered today: {tickers_entered_today}

INPUTS
- Rails (per-buy, USD): MIN={min_buy}, TYPICAL={typical_buy_low}-{typical_buy_high}, MAX={max_buy}
- Rule: After all actions, ≤5 total holdings (unique tickers).
- Holdings (canonical P&L): {holdings}
- Summaries (include visual/sentiment cues): {summaries}
- Momentum Recap (scorable only): {momentum_recap}
- Feedback Snapshot: {feedback_context}

PORTFOLIO GROUNDING
- Treat Holdings as the only source of truth for owned positions.
- Build the holdings set before deciding. You may SELL or HOLD only tickers shown in Holdings.
- If Holdings is empty or cash-only, do not output SELL or HOLD. You may BUY qualified setups or stay in cash with cash_reason.
- Summaries, headlines, Momentum Recap, memory, feedback, or prior prompts may mention tickers you do not own; those are not positions.
- If a ticker is not in Holdings, it can only be considered as a new BUY candidate, never as a HOLD/SELL.
- If Holdings shows repeated symbols or multiple lots, reconcile them into one net ticker exposure. Output at most one net action for that ticker.

PLAN (concise)
- Step 1: Inventory quarantine and A/B/C triage before new entries.
  • Inherited/synced positions are not validated alpha. Rebuild the thesis from current data only.
  • A-quality HOLD: fresh intraday/≤24h catalyst, above VWAP/opening range, strong 10m trend, relative strength vs SPY/sector, abnormal volume, near highs.
  • B-quality HARVEST/TRIM: profitable but stale, extended, crowded, losing momentum, or catalyst no longer being rewarded.
  • C-quality EXIT: no fresh catalyst, failed/stale catalyst, below VWAP, weak/flat 10m trend, near lows, weak relative strength, or down >1–2% without confirmation.
  • If catalyst or relative-strength fields are missing or vague, count them as unconfirmed rather than assuming strength. But intraday micro-signals (VWAP, 10m/1h trend, abnormal volume) are routinely unavailable near the open and for pullbacks — their absence is EXPECTED and must NOT count against a setup; confirm via the reliable signals instead.
- Step 2: Profit harvesting discipline.
  • Any holding ≥ +3% above cost is a default SELL full/majority unless a fresh ≤1 session catalyst is still price-confirmed.
  • Winners +3–5% with stale momentum should fund tomorrow’s ammunition.
  • If crowd/media euphoria is obvious and price is extended, fade by harvesting.
- Step 3: Loss containment.
  • Do not let stale/no-catalyst losers drift to -6% to -8%.
  • For synced/inherited holdings, if down >1.0–1.5% with below-VWAP or weak/flat 10m trend and no fresh catalyst, SELL full/majority.
  • If any holding is down >2% and catalyst is stale/failed or tape is weak, SELL full or at least majority.
  • Never average down a failed catalyst in a cash account.
- Step 4: New BUY filter.
  • Require a real reason to own: EITHER a fresh/intact catalyst OR a valid pullback/reversal setup, PLUS relative strength and a constructive multi-day/monthly trend. Intraday confirmation (opening-range/VWAP/10m/1h trend, abnormal volume) is a BONUS when available — NEVER a requirement; it is routinely absent near the open and for pullback names, and its absence must not block a buy.
  • Also require the setup not to be a chase of a move that already happened. HARD ANTI-CHASE (block genuine post-pop exhaustion, NOT ordinary strength): REJECT as a chase only when the move has CLEARLY already happened — up ≥8% on the day, a vertical gap or parabolic spike, or a climactic top-of-range push on exhaustion/declining volume. Do NOT reject a name merely for being green, sitting high in its day range, or near a 52-week high — strong stocks trend at their highs. A modest daily gain (≈ ≤6%) with a positive 10m/1h trend, a fresh catalyst, and adequate (≥ ~0.8x) volume is a NORMAL entry you SHOULD take when it ranks among your best — not a chase. FRONT-RUN instead: prefer oversold reversals, pullbacks into support / VWAP reclaim after a flush, and accumulation BEFORE the catalyst is obvious. Markets are manipulated; the engineered breakout-near-highs is bait — sometimes do the opposite of the crowd.
  • Prefer 2–3 ranked contrarian R1..Rk setups within rails.
  • Avoid ATH chases, headline-only hype, stale media narratives, weak 10m tape, and names near intraday lows without reversal confirmation.
  • Do not rotate into the same narrative you just cut unless the new ticker has materially better fresh confirmation.
  • Do not both sell and buy the same ticker in one response; choose the net risk-reducing action.
- Step 5: Cash account behavior.
  • If Mode is CASH, treat every BUY/SELL as part of a 1–5 trading day swing.
  • Avoid same-day churn unless the thesis breaks, risk becomes unacceptable, or a mechanical rule forces action.
  • Cash is valid when no setup clears the filter.

OUTPUT (STRICT)
- Return ONLY a JSON object with:
  • a decisions array of trade actions, and
  • optionally a top-level "cash_reason" string.
- Each decisions element: {"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"≤140 chars; momentum + catalyst; contrarian crowd read; BUYS prefixed R1..Rk"}
- No extra keys, no commentary outside JSON.

CASH REASON REQUIREMENT
- If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value} and min buy ${min_buy_amount}), you MUST add a top-level "cash_reason" string.
- That cash_reason must briefly explain BOTH:
  1. Why no new BUY was taken, such as ticket caps hit, min-buy not met, cooldown, holdings cap, or no qualified fresh/confirmed setups within rails, AND
  2. What you did about any holdings ≥ +3% above cost, such as harvested a winner or held only because a fresh 1-day catalyst remains price-confirmed.
- Keep the JSON object compact: the decisions array, a top-level "considered" array (the 2-3 setups you actually weighed this cycle, each {ticker, signals, verdict, why}), plus an optional cash_reason.

REMINDERS
- Always respect settled-funds constraints for BUYS in cash accounts.
- Always respect the ≤5 unique holdings cap after all actions.
- Prefer selling +3–5% winners when momentum/catalyst freshness fades.
- Cut synced/stale/no-catalyst losers early, especially below VWAP or with weak/flat 10m trend.
- A setup is confirmed by the RELIABLE signals it has — multi-day/monthly trend, relative strength, 20-day MA / range position, the pullback/reversal setup, and catalyst. Missing intraday micro-signals (VWAP, 10m/1h trend, abnormal volume) do NOT mean 'no edge' — they are frequently unavailable near the open and for pullbacks.
- For BUYs, do not confuse a headline with a tradable catalyst; require price confirmation.
- Explicitly mention crowd behavior you are fading when relevant.
- Do NOT output anything except the JSON object described above.