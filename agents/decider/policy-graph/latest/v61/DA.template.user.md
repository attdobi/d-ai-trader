---
id: DA.template.user
version: DeciderAgent.9ea09b9as.v61
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
provenance: prompt_versions#667
sep_before: ""
sep_after: ""
body_sha256: 8378cc715f43e28e4a1095a49097261231e85efcebc9c05672ea6e98f3a30e40
tags: []
tickers: []
---
ACCOUNT
- Mode: {account_mode}
- Settled funds: ${settled_cash}
- Per-BUY rails: MIN=${min_buy}; TYPICAL=${typical_buy_low}–${typical_buy_high}; MAX=${max_buy}
- Whole shares only. For ordinary half-size trades, the existing one-share allowance applies only when that share is within MAX. An earnings-event hard cap may never be exceeded to buy one share.
- After all actions, at most 5 unique held tickers.

DAILY STATE
- Tickets used / cap: {today_tickets_used}/{daily_ticket_cap}
- BUYs used / cap: {today_buys_used}/{daily_buy_cap}
- Minutes since last new entry: {minutes_since_last_entry}
- Tickers entered today: {tickers_entered_today}

SUPPLIED EVIDENCE
INDEX REGIME
{index_regime}

EVENT CALENDAR
{event_calendar}

HOLDINGS — the only authoritative ownership record
{holdings}

SUMMARIES
{summaries}

MOMENTUM RECAP
{momentum_recap}

CONTRARIAN WATCHLIST
{contrarian_watchlist}

QUARANTINE
{quarantine}

FEEDBACK SNAPSHOT — evidence subordinate to current policy
{feedback_context}

DECISION CHECKLIST
1. Establish confirmed ownership and current account limits. A blank/unreadable regime is MIXED.
2. Apply current holding-exit rules before new entries. Do not confuse a recent system entry with a synced/inherited holding.
3. Audit the best 2–3 supplied BUY candidates, applying the current policy rather than old numeric thresholds from memory. Rank passing candidates R1..Rk.
4. Distinguish ordinary entries, after-release price-confirmed opportunities and intentional earnings_event entries. For the latter, name the verified date and explicitly acknowledge holding through the release and full-notional gap risk; the server must confirm eligibility and the hard dollar cap.
5. Check settled funds, whole shares, rails, ticket/BUY/position limits, regime and macro allowances, extension, priced kill, quarantine and correlation. Event-strategy exceptions do not waive those independent limits.
6. Return the system's exact JSON contract, with valid cited IDs. Audit every holding and each weighed candidate. Mark unavailable facts UNKNOWN.

SIGNALS CARD
Use these facts where actually supplied: ownership state; regime; setup; extension above the 20-day MA; day/1-week/1-month change; relative strength; RSI; numeric K and D; catalyst source/status/date; quarantine; correlation count; sessions to the ticker's own earnings. Do not manufacture missing fields.

CASH DISCLOSURE
If there are no BUYs while settled funds are available (settled funds ${settled_cash_value}; minimum BUY ${min_buy_amount}), include cash_reason. Explain the best candidates' concrete failures and any owned winner at or above +3%. A regime label or scheduled macro event alone does not establish that every candidate failed.
