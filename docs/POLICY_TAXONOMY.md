# Source-grounded market taxonomy

The taxonomy organizes recorded evidence. It does not turn a repeated headline,
a model hypothesis or a later winning trade into an approved trading rule.

## Why geopolitical groups looked empty

The original Learning map grouped immutable guideline text and bounded saved
Decider rationale, with same-version citation links. It excluded the six-source
summary history. Feedback focuses on trade diagnostics and compressed proposals;
it does not systematically reconstruct theme-specific news episodes and their
matched outcomes. General instructions consequently dominated the visible graph.

The updated weekly Feedback path now adds config-scoped topic counts and up to
eight 500-character source excerpts for its existing lookback window. Source
reports remain untrusted, repeated stories remain correlated, and missing
theme-linked candidate/outcome data is explicitly a research gap. The reviewer
may propose an evaluation; it cannot promote an invented geopolitical BUY/SELL
rule from headline frequency. This dynamic context loads with the updated
Feedback code on the application's next normal restart.

The October 29 audit found 569 saved summary rows containing Iran and 227
containing Hormuz across the available April–October history. These are raw text
mentions, including repeated stories and uncertain reports. No long-term memory
row explicitly mentioned Iran, Hormuz, oil or energy. The absence of a learned
rule and the absence of an observed topic are different findings.

The 90-day parsed inventory contained 1,672 saved summaries and 20 scoped Feedback
records. It counted 217 Iran/Middle East news observations, 45 Hormuz observations
and 653 Energy observations. Iran/Middle East is broader than literal Iran text.
The topic counts overlap, include risks/denials/hypotheses and do not count
independent events. Three feedback hypotheses mentioned Energy; none mentioned
the geopolitical groups. Source coverage is reported separately from display
sampling and from prospective trading-quality denominators.

## Hierarchy and evidence layers

`policy_graph/taxonomy.py` defines `market_taxonomy_v2_2026_10_29`; legacy IDs remain
available. Geopolitics contains Iran/Middle East, conflict/diplomacy and sanctions.
Trade/shipping contains Strait of Hormuz and shipping/supply disruption. Energy
contains oil/gas. Technology contains AI, semiconductors and EVs; semiconductor
topics contain memory manufacturing. Broad electricity/energy text does not
automatically imply oil. Generic conflict does not automatically imply Iran.

`themes.py` assigns multiple literal topic matches and ancestor memberships.
Curated issuer exposure, direct guideline text and same-version cited-case
associations remain labeled separately. Saved news never assigns a subject to an
otherwise general policy node. Frozen embedding coordinates are unchanged; these
groups are descriptive organization, not a learned decision boundary.

`observation_inventory` reads only allowlisted summary and scoped Feedback text,
never raw prompts, account state, screenshots or unscoped manual responses. Its
counts cover the declared window and safe parsed scanned records, capped at
10,000 rows per source. A balanced display sample defaults to 120 records. Source
IDs, text hashes, dates, claim status and sample/scan truncation remain explicit.
The Learning map shows source excerpts separately from guideline dots and trade
cases. Parent/child and cross-theme counts must not be summed as unique stories.

## One Sol review, then stable classification

The first explicit `review_market_taxonomy.py --config-hash 9ea09b9as --run` sent
sixteen bounded saved news excerpts to `gpt-6.1-sol`. The request had no tools,
automatic retries, screenshots or trading instructions. It returned twelve
organization proposals, including existing geopolitics/Hormuz/oil categories and
possible additions for energy-linked issuer exposure and cloud service outages.
Every supporting quote was checked as an exact substring of its supplied source
record. A grounded quote verifies traceability, not the truth of the report.

Audit row 1 in `policy_taxonomy_reviews` records source hash
`b7f7b363da7bf8fa66139a6891f1bb5de54ea0a0a5b9540750a904e43554fac9`,
4,817 input tokens and 2,459 output tokens (495 reasoning tokens included), costing
$0.034224 at the standard local tariff. The model saw a selective news sample,
not all 1,692 source records or separate feedback hypotheses. Its limitations
remain in the audit. Proposed new categories are not silently installed.

The CLI previews by default; `--run` explicitly performs the paid review. Reusing
the same latest frozen source sample skips another request. Audit rows are
immutable and configuration-scoped. Viewing the map makes no hosted model call.

Classify new saved observations with the stable taxonomy on the fly. Periodically
review unclassified records, changing vocabulary and coverage gaps. Propose a
versioned addition when justified; keep unknowns rather than inventing a precise
topic. Do not recreate labels and IDs each cycle. A future theme-specific trading
lesson needs decision-time source links, a declared eligible candidate universe,
matched comparisons, net outcomes and later independent evidence before reviewed
policy promotion.
