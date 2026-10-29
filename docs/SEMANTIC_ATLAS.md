# Semantic learning landscape

The Learning map's default view is a map of recorded text. Its visual treatment
borrows the RUSH demos' density contours, prominent region labels and focused
evolution trails. Every plotted point comes from an immutable guideline revision
or a scoped saved source observation; decorative fake samples and invented
BUY/PASS boundaries are not plotted.

## Actual embeddings and a nonlinear reference

`build_semantic_atlas.py` sends scoped text to the existing loopback Nomic model
through the local embedding client and shared cache. News embeddings prioritize
the three actual headlines so repeated missing-data scaffolding does not dominate
the geometry. The full original text remains available in the inspector.

The projection uses deterministic PCA preconditioning, then real scikit-learn
t-SNE with cosine distance, seed 42, perplexity up to 30 and 1,000 iterations.
KMeans metadata is computed from the original normalized embeddings. Top-six
cosine neighbors also come from that original space. [The scikit-learn t-SNE
reference](https://scikit-learn.org/stable/modules/generated/sklearn.manifold.TSNE.html)
describes the algorithm and its parameters. Projected distances and apparent
cluster sizes are descriptive; they are not market risk, payoff or calibrated
decision-quality measures.

The October 29 local references contain:

| Agent | Guideline revisions | Sampled observations | Total | Embedding neighborhoods |
|---|---:|---:|---:|---:|
| Decider |295|150|445|9|
| Summarizer |135|150|285|7|
| Feedback |126|150|276|7|
| Company |20|150|170|5|

All used `text-embedding-nomic-embed-text-v1.5` and no hosted inference. The
browsing inventory normally samples 120 observations, independent of build
sampling. Displayed counts therefore differ from the complete fitted reference.
The Decider reference ID is `6287e5bb6da5f0f4f65dd528`, with recorded KL divergence
0.5355131626. That fit statistic is not a trading score.

## Two taxonomy facets

`atlas_taxonomy.py` adds `semantic_atlas_facets_v1_2026_10_29` alongside the existing
versioned market taxonomy. Policy capabilities describe a rule's function:
Entries & setups, Risk & exits, Capital & portfolio, Events & earnings, Evidence
quality, Learning & feedback, and Mission & identity. Market display families group
source-grounded geopolitics/trade, energy/supply, AI/compute, technology, mobility,
corporate catalysts, macro and other reports. Existing canonical IDs and paths
are preserved; for example, Mobility is a useful display family without silently
rewriting the earlier EV taxonomy's parent.

Assignments record title/identifier/body matches or a field fallback. News never
runs through the policy-capability classifier, and missing-data scaffolding does
not create a macro event. A primary color is a display choice; multiple source
topics remain inspectable. General stop rules do not acquire an invented Iran
association.

The visible contour islands are Gaussian density estimates over the actual
projected members of each display family. Labels sit near observed density
peaks, with collision avoidance. The high-dimensional unsupervised neighborhood
metadata remains separate. Colors/categories annotate the geometry and never
move the points. Small geopolitical and energy groups retain prominent labels.

## Stable history and source inspection

The reference uses all fitted immutable revisions. Playback changes the active,
added, modified and retired markers; older texts are faint when enabled. Curved
trails connect actual revisions. Selecting an older revision opens an exact
recorded version rather than silently substituting today's text.

The backdrop remains fixed for orientation. When viewing an earlier policy,
visible news points must be dated on or before that revision. Two aware dates are
compared as instants; two naive logged dates use their shared wall-clock ordering.
Mixed or missing timezone evidence is omitted and counted, not guessed. The
reference geometry is the current visualization corpus, not a reconstruction of
what an old model knew or a causal explanation for a past trade.

Shapes distinguish guidelines, news and feedback hypotheses. Inspectors retain
source IDs, timestamps, hashes, taxonomy basis and original text. Source reports
remain unverified observations. Neither proximity nor density validates a
trading lesson or a decision boundary.

## Local build and refresh

```bash
./dai/bin/python build_semantic_atlas.py --config-hash YOUR_CONFIG --agent all
```

Artifacts live at
`agents/<agent>/policy-router/<config>/semantic-atlas.json` and are ignored by Git.
The original `learning-projection.json` is preserved. The CLI defaults to actual
local semantic embeddings and stops if they are unavailable. An explicitly
requested `--lexical-fallback` produces clearly labeled word-feature t-SNE;
corpora smaller than four texts use honestly labeled PCA. `--refit` is an explicit
new reference; preserve a needed prior artifact before intentionally refitting.

Normal map GETs read cached coordinates only and do not invoke embedding models,
fit projections or place orders. **Refresh map** sends an explicit same-origin
POST to `/api/policy-graph/learning/atlas-refresh`, and polls a scoped job status.
One local worker permits at most four active/queued jobs, deduplicated by
configuration and agent. The worker requires an existing semantic reference and
uses fixed loopback Nomic settings with no hosted fallback. New points use a
labeled nearest-reference approximation; all previous coordinates stay fixed.
An unavailable model, capacity limit or invalid cache leaves the prior map intact.
The corpus is bounded at 700 points. No policy, trade, router mode, or shadow
evaluation window changes through this interface.
