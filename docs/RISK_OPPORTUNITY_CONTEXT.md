# Risk pressure and opportunity context

## What the landscape measures

`event_calendar.py` computes a bounded, hand-weighted 0–100 score from the technical
index regime, scheduled macro proximity and holdings with upcoming earnings.
It does not estimate fair value, upside, loss probability, realized volatility,
liquidity or the portfolio's dollar risk. Watchlist earnings are supplied for
individual candidate review; they do not increase the holdings score.

For October 29, 2026, the unchanged weights yield **65 = RISK-OFF 55 + post-FOMC
10**, before any applicable holding-earnings points. The October 28 release is
past, so `MACRO WINDOW: no` is consistent with that residual pressure. The
[Federal Reserve schedule](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
records the October 27–28 and December 8–9 meetings. Score-part labels now name
the event that actually contributes points, rather than labeling a post-release
contribution with the next meeting's date.

The current dashboard card uses today's latest recorded regime and recomputes
calendar context with cached earnings. Historical points use each day's maximum
recorded score when available; otherwise they are reconstructed. The card can
therefore differ from the curve's latest daily maximum. The future tail holds
the current regime and known holdings schedule fixed; it is a conditional
calendar projection, not a market or profitability forecast.

The dashboard now shows score components and known/unknown earnings coverage.
An unavailable company date is not evidence that the next five sessions are
event-free. Calendar warnings identify their horizon and each calendar's last
known date. The built-in CPI and Employment Situation tables were extended using
the [official BLS 2027 release schedule](https://www.bls.gov/schedule/2027/home.htm),
published October 9, 2026. The October 29 warning was stale data, not an unknown
event inside the immediate trading window. Future exhaustion remains explicit.

## How the agents receive it

| Stage | Information and role |
|---|---|
| Summarizer sweep | `run_summary_agents` freezes one macro-only snapshot for the sweep and passes it explicitly through workers, page capture and `get_openai_summary` |
| Each Summarizer | News HTML/images plus the same dated operator calendar: next/recent FOMC, CPI and jobs, release times, sessions-to, macro-window flag and coverage |
| Decider | Fresh regime, holdings, screener/entity watchlist, the full event-calendar block and a separate capped earnings-event contract |
| Router | Event context is a relevance feature; the existing shadow comparison does not prune the served prompt, and optional memory routing does not remove core policy |
| Feedback | Reviews saved decisions, outcomes and context, with supplied-calendar coverage separated from news/model-text mentions |

Before this change, the Summarizer prompts requested calendar details but the
request assembler supplied only news and screenshots. The agents could correctly
return `not_shown` when a source omitted those dates. The Decider already received
the independent computed calendar, so a missing date in a summary did not mean
the Decider had no calendar.

`summary_event_context.py` supplies pure local calendar facts with one context ID
and UTC/ET timestamps. It adds no model call, database read, broker request or
earnings-provider request. It supplies no guessed regime, portfolio score,
holding state, company earnings or sizing allowance. Standalone summary calls
build the same bounded fallback. Disabled/unavailable calendars remain unknown.

The existing headline/card/insights schema and word budget are preserved. The
model is instructed to identify operator-provided calendar context separately
from observations in the news. The saved outer `operator_calendar` object is
allowlisted, copied metadata with
`evidence_role=provided_operator_context_not_news_observation`; it cannot be
substituted for evidence that a publisher reported an event. The Summarizer's
code scaffold is inspectable as `SA.code.operator_calendar` in Policy Graph.

## Pressure and opportunity are separate judgments

The numeric risk score has no standalone `score >= X` execution veto in the
traced runtime. The approved instructions permit selective risk-off and
macro-window entries within their existing size and setup restrictions. Saved
decisions confirm that HIGH pressure has coexisted with BUY proposals; later
cash decisions can fail independent funding, earnings or stop-geometry gates.
This demonstrates use of the context, not a proven profitable edge.

The charter now says explicitly:

- Pressure describes exposure and timing, not a buy/sell threshold or valuation.
- Supplied support/reversal structure, relative strength, catalyst or valuation
  evidence and invalidation plans must be assessed within the current limits.
- A lower price or a price below its moving average does not establish
  fundamental undervaluation. Unknown valuation does not by itself reject an
  otherwise qualified technical setup.
- Support, fair value, upside or a tighter stop must never be invented to pass
  a gate. No score reading forces a trade.

The audit also corrected a contradictory screener default and the watchlist and
Decider confirmation stop scaffolds.
“Cash is the correct default” conflicted with selective-entry guidance. The old
`K = higher(20-day MA, 3% reference)` could put K above entry for an oversold name.
An above-entry MA is a reclaim/resistance reference. A protective K needs genuine
evidenced geometry below entry and a positive distance within the active cap.
The printed 3% reference remains descriptive and grants no exemption. Candidate
ranking is not a requirement to buy an otherwise ineligible candidate.

No numerical weights, entry-distance cap, holding loss cap, position sizing,
settled-funds limit, minimum buy, quarantine, harvest rule or earnings-event
permission was relaxed. Some strategy rules remain model-followed prompt rules;
ownership/cash/amount validation and explicit earnings-event authorization have
independent runtime checks. This work does not claim every textual strategy
gate is deterministically enforced.

## Learning and evaluation limits

The old event-acknowledgment diagnostic scanned the entire saved summary JSON.
The new operator metadata would therefore create apparent event mentions merely
through its keys. The diagnostic now separates provided-calendar context from
allowlisted model/news text. Repetition of supplied facts is not new independent
evidence or proof of improved decision quality; historical and enriched cohorts
need their provenance labels preserved.

Loading the new context assembly is itself a deployment change. Router quality
comparisons must use matched recorded policy/context, rather than attributing
before/after aggregate wins to the router or calendar enrichment.

Existing retrospective macro-entry buckets estimate entry dates from sale dates
minus holding days. They are coarse associations. They do not calibrate this
score or show that high pressure predicts gains. Testing that hypothesis needs
prospective decision-time cases, independent future outcomes, the supplied
candidate universe and like-for-like comparisons, with costs and missingness
disclosed. The learning map and taxonomy organize those observations; they do
not establish a decision boundary by themselves.

The code and read-only preview can be inspected immediately. Existing long-running
trader processes need their normal restart to load changed Python prompt/context
assembly. This audit does not restart the trader, activate a database prompt
version, place an order or run a paid model probe.
