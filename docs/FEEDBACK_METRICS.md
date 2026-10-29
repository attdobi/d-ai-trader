# Feedback dashboard metrics

## Scope and time windows

`/api/feedback` reads the active configuration's saved `trade_outcomes` rows.
Every requested lookback shares one UTC `as_of`. An N-day window is the inclusive
interval `[as_of - N × 24 hours, as_of]`; it is not a calendar week. A sale earlier
on the same weekday last week can therefore be outside the seven-day window.
Future rows and explicit no-trade placeholders are excluded. The ledger stores
naive UTC timestamps; the API labels them explicitly and the UI converts dates
for local display without treating UTC as local time.

One observation is one recorded closure row. A partial sale or separate lots can
produce several rows, so this is not a count of independent purchases or complete
round trips. There is no guessed deduplication. Open holdings, passed candidates,
paper opportunities and router comparisons are not part of this denominator.

`feedback_metrics.py` reads the widest requested interval once, then computes
nested windows from that same scoped snapshot and cutoff. Dashboard reads do not
run the Feedback model, initialize tracker tables or change the learning policy.
The existing learner's separate analysis path is preserved.

## Closure metrics

| Metric | Definition |
|---|---|
| Scored closures | Recorded closure rows with a finite return fraction |
| Win rate | Strictly positive return fractions divided by scored closures |
| Mean return | Unweighted arithmetic mean of scored return fractions |
| Wins / losses / flat | Return fraction greater than / less than / equal to zero |
| Unscored | Recorded closures whose percentage return is missing or nonfinite |
| Recorded P&L | Sum of recorded dollar gains for scored closures; unavailable if any required dollar value is missing |

Stored return fractions are multiplied by 100 exactly once for percentage
display. The recorded dollar field is a price-based entry/exit difference times
shares; it has no separate fee adjustment. Empty cohorts have unknown rates and
means, not fabricated zero performance. Each window exposes its exact dates,
counts, counting unit, first/last scored close and definitions.

The column charts compare overlapping samples, rather than suggesting a sequence
of independent daily returns. Sample size appears under every column; the
shortest-window summary remains visible. The audit table provides exact cutoffs
and dollars. Range-request sequencing prevents an older response from replacing
the selected range.

Hovering a win-rate column also shows **N** and a two-sided **95% Wilson binomial
confidence interval**, calculated from the exact win/closure counts. For example,
2 wins out of 2 gives approximately 34.2%–100.0%, rather than zero uncertainty at
an observed 100%. Empty or invalid counts have no interval. See the
[NIST Wilson formula](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
The same information is available by hovering the visible shortest-window
summary. No error bars or additional chart panel are added.

The interval is illustrative: the binomial model assumes independent trials with
a common win probability. Related lots/trades and changing market regimes can
violate those assumptions. It is not a confidence interval for mean trade return
or a forecast of future profit; the mean-return panel retains its sample count
without reusing the win-rate interval.

The donut and streak use the latest 50 recorded closures and refresh with the
table. The donut uses stored outcome categories: the separate dollar-based
break-even bucket can include a small positive or negative return. Streaks use
strictly positive/negative percentage returns; flat or unscored closures break a
streak. Unknown categories remain unclassified. Table sorting binds once and
retains the selected ordering across refreshes; unknown numbers display as
unknown, and a recorded zero holding duration stays zero.

Saved Feedback reviews describe their original analysis sample and recorded
timestamp. Their percentages use the same fraction conversion. A review with no
closed-trade sample does not display its legacy synthetic success value as an
observed win rate. Current lookback charts still load if no review exists.

## Account and benchmark comparison

The portfolio uses saved daily valuations and geometrically linked,
cash-flow-adjusted returns. The daily formula assumes an end-of-step flow:
`r = (ending value - external flow) / beginning value - 1`. Because exact
flow-time valuations are unavailable, settlement attribution assigns transfers
to nearby observed steps by value-change fit. This is an approximation; the
[GIPS methodology guidance](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)
explains why valuation timing around external flows matters for time-weighted
returns. This dashboard does not claim GIPS compliance.

Dates use the recorded snapshot convention. Curves stop at common observed
endpoints, and internal missing valuation sessions appear as gaps. Daily Sharpe
is unavailable when missing sessions make portfolio returns span multiple
benchmark sessions. The annualized ratio otherwise uses sample daily volatility,
252 periods per year and a zero risk-free rate. Drawdown is measured from observed
index peaks, so unobserved intraday drawdowns are outside its scope.

SPY/VTI use dividend-adjusted closes; DJIA/NASDAQ are price indexes. A benchmark
without both common endpoints is omitted and disclosed. “Return spread” is
system cumulative return minus benchmark return, in **percentage points**; it is
not regression-based alpha. The chart reports missing data, heuristic V-shaped
snapshot filtering and cash transfers explicitly.

Trade profit factor uses finite recorded dollar gains/losses. Mean trade return
uses finite percentage returns; separate cohort sizes and missingness are
reported. These closure statistics use the actual chart's observed date span,
which can be shorter than the requested range when data is stale.

## Event-risk landscape

The 0–100 score is a calendar heuristic, not a calibrated probability of loss.
Historical days with recorded Decider snapshots use that day's maximum recorded
score and the corresponding regime/macro-window flag. Level labels derive from
that same score. Other historical days are reconstructed; the future tail is a
calendar projection at the current estimated regime. These sources stay labeled
separately in the DTO and tooltip.

Fill markers use Eastern trading-session dates and sit on the daily aggregate,
not an inferred exact fill-time risk score. Future records are excluded. A sale
with an unknown return has a neutral unscored marker; a zero return is flat,
not a win. Calendar coverage gaps remain explicit. The graph does not change
entry permissions, risk limits or the separate earnings-event strategy.
