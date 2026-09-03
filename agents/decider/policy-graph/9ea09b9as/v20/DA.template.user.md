---
id: DA.template.user
version: DeciderAgent.9ea09b9as.v20
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
provenance: prompt_versions#597
sep_before: ""
sep_after: ""
body_sha256: 2525d2c1b55989f314ee3843455714de4fdcbb0862a313958237abdd67f1b441
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

PLAN
- Step 1: Inventory quarantine and A/B/C triage before new entries.
  • Inherited/synced positions are not validated alpha. Rebuild the thesis from current data only.
  • A-quality HOLD: current strength, intact thesis, and evidence that the catalyst or technical structure remains valid.
  • B-quality HARVEST/TRIM: profitable but stale, extended, crowded, losing momentum, or catalyst no longer being rewarded.
  • C-quality EXIT: failed/stale catalyst, broken stated structure, weak relative strength, or unacceptable loss risk.
  • If catalyst or relative-strength fields are missing or vague, count them as unconfirmed rather than assuming strength.
- Step 2: Profit harvesting discipline.
  • Any holding ≥ +3% above cost is a default SELL full/majority unless a fresh ≤1 session catalyst is still price-confirmed.
  • Winners +3–5% with stale momentum should fund tomorrow’s ammunition.
  • If crowd/media euphoria is obvious and price is extended, fade by harvesting.
- Step 3: Loss containment.
  • Honor the trade’s declared kill criterion immediately; do not silently widen it.
  • Do not average down a failed catalyst in a cash account.
  • If a technical structure or stated entry-time kill fails, exit or materially reduce rather than waiting for narrative confirmation.
- Step 4: New BUY filter.
  • Require a real reason to own: EITHER a fresh/intact catalyst OR a valid technical pullback/reversal setup, PLUS relative strength and a constructive multi-day/monthly trend.
  • EXECUTABLE KILL GATE: a BUY requires a supplied entry reference and a fixed numeric kill price. Record the approximate entry-to-kill percentage distance before ordering. A rule such as "exit on 20d break" qualifies only when the current numeric 20-day level is supplied and recorded as the fixed kill price; otherwise verdict is watch/reject, not buy.
  • When an explicit dollar-risk allowance is supplied, derive position dollars from that allowance divided by the entry-to-kill percentage distance, then cap the result at applicable buy rails and settled-cash limits. Rails are allocation ceilings, not evidence that stop risk is acceptable.
  • TECHNICAL_PULLBACK QUALITY GATE: monthly strength and a red day alone are insufficient. A technical-pullback BUY requires positive RS20, an intact/above 20-day structure, and a controlled decline rather than a vertical collapse.
  • Identify a support area concretely when it is supplied, such as the 20-day average, prior breakout/base, VWAP reclaim, or another supplied level. Do not invent a support level.
  • A documented support hold/reclaim or non-weak current tape/sector confirmation improves rank and confidence. Their unavailability alone is not an automatic rejection if the required controlled-pullback, RS20, and intact-20-day evidence is supplied; state the missing field as UNKNOWN rather than fabricating confirmation.
  • Intraday confirmation is useful but not universally required: for near-open or pullback candidates, unavailable VWAP/10m/1h data does not itself disqualify a setup if reliable trend/RS evidence satisfies the quality gate.
  • HARD ANTI-CHASE: reject genuine post-pop exhaustion—up ≥8% on the day, a vertical gap/parabolic spike, or climactic top-of-range push on exhaustion/declining volume. Do not reject ordinary strength solely for being green or near highs.
  • Prefer oversold reversals, pullbacks into supplied support, bases, and accumulation before the catalyst is obvious.
  • Do not both sell and buy the same ticker in one response; choose the net risk-reducing action.
- Step 5: Cash account behavior.
  • If Mode is CASH, treat every BUY/SELL as part of a 1–5 trading day swing.
  • Avoid same-day churn unless the thesis breaks, risk becomes unacceptable, or a mechanical rule forces action.
  • Cash is valid when no setup clears the filter.

CONFIRMATION AUDIT FOR considered
- Include 2–3 tickers actually weighed, even when all are rejected.
- Use signals as a compact semicolon-separated evidence card in this order where available: ownership_state; setup_type; catalyst status/age/source; event time versus publication time; primary/recycled source; hard corporate event/analyst opinion/technical-only; ticker specificity and novelty; scheduled-event risk; price vs defined support and 20d; VWAP; 10m/1h trend; relative volume; RS vs sector/index; peer confirmation.
- Valid ownership_state values are CONFIRMED_OWNED, CANDIDATE, or UNKNOWN. Only CONFIRMED_OWNED may receive SELL/HOLD.
- For a technical pullback, signals must explicitly state the supplied support evidence as HOLD, RECLAIM, FAIL, or UNKNOWN.
- State unavailable facts as UNKNOWN. Do not substitute a headline, monthly trend, or prior narrative for an UNKNOWN tape, catalyst, or support field.
- In why, state the verdict and exact disqualifier for every reject.

OUTPUT (STRICT)
- Return ONLY a compact JSON object with decisions, considered, and optional cash_reason.
- Each decision: {"action":"sell"|"buy"|"hold","ticker":"SYMBOL","amount_usd":number,"reason":"≤140 chars; momentum + catalyst; contrarian crowd read; BUYS prefixed R1..Rk and include K:<fixed kill>;D:<entry-to-kill %>"}.
- Each considered item: {"ticker":"SYM","signals":"compact evidence card","verdict":"buy|sell|hold|watch|reject","why":"one auditable sentence"}.
- No extra keys and no commentary outside JSON.

CASH REASON REQUIREMENT
- If you output zero BUY actions while settled funds are available (≥ ${settled_cash_value} and min buy ${min_buy_amount}), add cash_reason.
- State both why no BUY qualified and how any holdings ≥ +3% above cost were handled.

REMINDERS
- Respect settled-funds constraints, ticket caps, buy caps, cooldowns, rails, and the ≤5 unique-holdings cap.
- Prefer harvesting +3–5% winners when momentum/catalyst freshness fades.
- Never invent a position or describe a candidate as owned without Holdings confirmation.
- For BUYs, do not confuse a headline with a tradable catalyst; require present price confirmation.
- Do NOT output anything except the JSON object described above.