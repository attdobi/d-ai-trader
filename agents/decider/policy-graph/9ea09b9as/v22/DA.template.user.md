---
id: DA.template.user
version: DeciderAgent.9ea09b9as.v22
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
provenance: prompt_versions#602
sep_before: ""
sep_after: ""
body_sha256: 6906d15ffdf9fc87498e06b86cc48c1d49b76bfd777d7fed6dc3b6f1604eaf3d
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
- Index Regime (if blank or a literal placeholder, treat as MIXED):
{index_regime}
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

PLAN
- Step 0: Regime. Read the Index Regime line and fix this cycle's allowance BEFORE looking at candidates: RISK-ON = up to 3 new BUYs, full rails; MIXED = ≤2 new BUYs at half size, extension ≤5%; RISK-OFF = cash default, ≤1 half-size BUY (oversold reversal or ≤3% above the 20d MA), harvest at +2%.
- Step 1: Inventory quarantine and A/B/C triage before new entries.
  • Inherited/synced positions are not validated alpha. Rebuild the thesis from current data only.
  • A-quality HOLD: current strength, intact thesis, price above its K: level, and evidence that the catalyst or technical structure remains valid.
  • B-quality HARVEST/TRIM: profitable but stale, extended, crowded, losing momentum, or catalyst no longer being rewarded.
  • C-quality EXIT: price at/below the K: in the buy reason (binding, first breach), failed/stale catalyst, broken structure, weak relative strength, or a fresh entry down ≥3% from cost.
  • Fresh-entry grace covers ordinary noise ABOVE the K: level only; it never overrides a priced kill.
- Step 2: Profit harvesting discipline.
  • Any holding ≥ +3% above cost (≥ +2% in RISK-OFF) is a default SELL full/majority unless a fresh ≤1 session catalyst is still price-confirmed AND the regime is RISK-ON.
  • Winners with stale momentum should fund tomorrow's ammunition.
  • If crowd/media euphoria is obvious and price is extended, fade by harvesting.
- Step 3: Loss containment.
  • The K:<price> recorded at entry is the trade's stop. Exit on the first cycle where price ≤ K. Do not widen it, do not wait for a close, do not "watch the 20d".
  • If a holding's reason carries no K: price (legacy entry), treat K = cost × 0.97 and act on it now.
  • Do not average down a failed thesis in a cash account.
- Step 4: New BUY filter (in this order; the first failure ends the evaluation and the verdict is watch/reject with that exact disqualifier).
  • QUARANTINE: the ticker is on the QUARANTINE line or was exited within 2 sessions → reject.
  • REGIME ALLOWANCE: this cycle's BUY count/size allowance from Step 0 is already used → reject.
  • EXTENSION CAP: % vs 20d MA >8% → reject (chase); 5–8% → half size, RISK-ON only; ≤5% → eligible.
  • SETUP: a controlled pullback in an uptrend (day −0.5% to −4%, not a vertical collapse; 1mo > +5%; RS20 > 0; RSI 40–63; holding or reclaiming the 20d MA) OR an oversold reversal (RSI < 38, turning up) OR a fresh, price-confirmed catalyst with relative strength and volume.
  • PRICED KILL: K = the higher of (20d MA level or stated support, current price × 0.97); D = its distance. D ≤3% full size, ≤6% half size, >6% pass. Missing VWAP/10m/1h never disqualifies; a missing K: always does.
  • CORRELATION: at most 2 semis / AI-infrastructure / quantum / space names at once, counting what you already hold.
  • DAY-TIMEFRAME ANTI-CHASE: up ≥8% on the day, a vertical gap/parabolic spike, or a climactic top-of-range push on exhaustion volume → reject. Green or near highs alone is not a chase.
  • Prefer oversold reversals, pullbacks into the 20d MA, bases, and accumulation before the catalyst is obvious.
  • Do not both sell and buy the same ticker in one response; choose the net risk-reducing action.
- Step 5: Cash account behavior.
  • If Mode is CASH, treat every BUY/SELL as part of a 1–5 trading day swing.
  • Avoid same-day churn unless the K: breaks, risk becomes unacceptable, or a mechanical rule forces action.
  • Cash is valid when no setup clears the filter — and in RISK-OFF it is the default.

CONFIRMATION AUDIT FOR considered
- Include 2–3 tickers actually weighed, even when all are rejected.
- Use signals as a compact semicolon-separated evidence card in this order where available: ownership_state; regime; setup_type; % vs 20d MA; day/1w/1mo %; RS20; RSI; K:<price>;D:<%>; catalyst status (fresh/stale/none, event time vs article time, primary vs recycled); quarantine status; correlation count.
- Valid ownership_state values are CONFIRMED_OWNED, CANDIDATE, or UNKNOWN. Only CONFIRMED_OWNED may receive SELL/HOLD.
- State unavailable facts as UNKNOWN. Do not substitute a headline, monthly trend, or prior narrative for an UNKNOWN field.
- In why, state the verdict and the exact disqualifier for every reject (e.g. "+11% above 20d MA = extension chase", "QUARANTINE: exited 08-25", "RISK-OFF allowance used", "K distance 7.4% > 6%").

OUTPUT (STRICT)
- Return ONLY a compact JSON object with decisions, considered, and optional cash_reason.
- Each decision: {"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"compact; setup + regime + % vs 20d MA; contrarian crowd read; BUYS prefixed R1..Rk and ending K:<price>;D:<%>"} Optional: "cited":["<guideline id>", …] — up to 4 ids from the GUIDELINE INDEX that drove the decision.
- Each considered item: {"ticker":"SYM","signals":"compact evidence card","verdict":"buy|sell|hold|watch|reject","why":"one auditable sentence"}.
- No extra keys except the optional "cited" list per decision (see GUIDELINE CITATIONS below); no commentary outside JSON.

CASH REASON REQUIREMENT
- If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value} and min buy ${min_buy_amount}), add cash_reason.
- Name the regime, the exact disqualifier of the best 2–3 candidates, and how any holdings ≥ +3% above cost were handled.

REMINDERS
- Respect settled-funds constraints, ticket caps, buy caps, cooldowns, rails, the ≤5 unique-holdings cap and the regime allowance.
- Prefer harvesting +3–5% winners when momentum/catalyst freshness fades.
- Never invent a position or describe a candidate as owned without Holdings confirmation.
- For BUYs, do not confuse a headline with a tradable catalyst; require present price confirmation.
- Do NOT output anything except the JSON object described above.