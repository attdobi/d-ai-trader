# Learning map

Open **Policy Graph → Learning map**. Three linked lenses connect policy text,
opportunity evidence and explicit policy comparisons. They never activate rules.

## Policy evolution

Each landmark is an exact revision of a guideline from a `prompt_versions` row.
Playback highlights additions, edits and retirements. Select a point for original
text, the previous revision's line diff, critic/human review and cited cases.
Structural containers and mutable long-term memory reconstructions are excluded
from this historical landscape. Citations remain associations, not causal P&L.

The existing local Nomic service supplies cached embeddings over loopback. A PCA
basis, reference identities and point coordinates are frozen in the ignored local
artifact `agents/<agent>/policy-router/<config>/learning-projection.json`. Future
revisions use the same basis and fixed axes. Filters and playback never refit it.
Both axes describe text similarity, not risk or profitability. A different model,
even with the same vector dimension, cannot silently share the old basis.

If local embeddings are initially unavailable, a clearly labeled word/bigram
projection is frozen instead. If an existing semantic service goes offline, old
points remain visible and new revisions await compatible vectors. To deliberately
rebuild, stop the dashboard, move its projection JSON aside and restart. This
changes the coordinate reference; record the change before comparing screenshots.
It does not change the policy. **Refresh evidence** makes read-only requests.
Reduced-motion preferences disable automatic playback but retain version steps.

## Opportunity evidence

Immediately before the Decider API call, the ledger freezes supplied screener
candidates and context tickers, input/run/policy identifiers, observation time,
features and reference-price provenance. Unknown spreads, tradability and market
quote timestamps remain unknown. Reference quotes never price paper entries.
The model's first action and citations are attached after its reply. These are
model observations, not order or fill confirmations. Response-only names are
postdecision and cannot expand prospective recall coverage. Historical decision
logs stay separate; they cannot acquire invented decision-time features/outcomes.

Paper specification `next_session_open_1_3_5_close_v1` uses:

- Adjusted daily open of the next NYSE session after observation as entry.
- Adjusted close of session 1, 3 or 5, counting the entry session.
- An assumed **10 basis points per side**, separate from actual fees and fills.
- Maturity after 17:00 ET on the required exit date. Missing bars, unavailable
  sources and unknown calendars remain unknown. The checked calendar currently
  covers 2026–2027; later years require calendar maintenance.
- Frozen matured outcomes with source, cost convention and measurement time.

Metrics use the complete prospective supplied-screener cohort in the declared
window, independently of display limits. Known holdings, quarantine and explicit
untradability are excluded; unknown tradability is not verified executability.
The first non-overlapping ticker episode is chosen before filtering assessment
or outcome readiness. A later favorable decision cannot replace an earlier miss.
Above the report's safety bound, rates are suppressed rather than computed from
a convenient partial sample.

For matured, explicitly assessed BUY/PASS cases, precision is profitable BUYs /
profitable-or-losing BUYs; recall is profitable BUYs / all profitable assessed
opportunities; FPR is losing BUYs / all losing assessed opportunities. Break-even
cases are separate. Coverage, maturity, sample sizes and Wilson intervals remain
visible. Net expectancy and normalized dollars per $1,000 are paper diagnostics,
not realized portfolio P&L, portfolio returns, drawdown or all-market recall.

The existing trader schedule launches bounded maintenance at **17:15 ET** in a
separate worker. Failed sources rotate through the queue so they cannot starve
newer cases. It never invokes the Decider or changes holdings. Restart the regular
trader to load both this schedule and prospective capture; restarting only the
dashboard does not load trader code. Do not start a second trader process.
Manual maintenance is also available:

```bash
./dai/bin/python update_prices.py --learning-outcomes --config-hash CONFIG
```

## Policy comparisons

Choose an incumbent saved-input version, cohort, candidate policy, assembly scope
and paper horizon. **Preview** validates exact inputs and reports model, reasoning,
changed rules and call count. Only explicit **Run** starts paid requests: at most
six saved inputs/twelve calls per dashboard job. Page loads never call a model.
The interface discloses the saved financial context and fixed OpenAI destination
before execution. Credentials and raw prompts never appear in public reports.

Both sides are recomputed on identical decision-time context and model settings.
Original observed actions remain distinct. Live news, current holdings, future
outcomes and current rule-health statistics do not enter replay requests. Frozen
cohort hashes reject changes after preview. Credential-shaped content, rewritten
incumbent rules, incompatible templates and ambiguous spans fail before calls.

Two scopes are supported:

- **Captured rule edits:** compatible edits to existing served rules, retaining
  the captured subgraph, code, memory and context.
- **Full policy:** render all stored policy fields on both sides, supporting
  appended/removed rules and rebuilt citation indexes. This is a declared
  full-policy comparison, not a recreation of production subgraph routing.

Provider errors/truncation remain unassessed. HOLD/SELL remain audit-only for
BUY/PASS quality. The actual provider model must stay consistent across both
sides. Usage is logged as `PolicyReplayAgent`; missing cache tariffs or unknown
costs stay unknown in the replay report. Standard-rate estimates elsewhere may
differ from cache-aware billing.

The report shows action flips and paired paper metrics on compatible matured
cases. It freezes its outcome snapshot: a replay run before maturity stays
unmeasurable; a later comparison can use matured records. Retrospective results,
especially a policy developed from those outcomes, do not establish forward
quality. Evaluate later independent periods. No replay activates a candidate.

CLI preview is read-only by default:

```bash
./dai/bin/python learning_replay.py --input-id INPUT_ID --candidate-version VERSION
```

`--assembly-mode full_policy` declares full-policy scope. `--execute` explicitly
permits the previewed paid requests. The CLI never prints keys or prompts.

## Implementation

`policy_graph/learning.py` owns history/projection; `opportunities.py` owns snapshots
and paper marks; `learning_replay.py` owns paired evaluations. The lazy OpenAI
adapter pins `https://api.openai.com/v1`, bounds output/time, disables retries and
uses no tools or model fallback. Tables are additive and configuration-scoped.
Raw replay requests remain in the local database. Presentation endpoints omit raw
prompts and raw replies.
