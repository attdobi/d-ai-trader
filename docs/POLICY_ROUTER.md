# Policy router

A Jev-like decision model for the Decider's prompt. For every **routable** node of a cycle (diary
entries and long-term memory rows by default, lessons opt in) it returns a typed decision:

```
{node_id, p, choice: include | exclude, confidence = |p - 0.5| * 2}
```

`p` is a calibrated probability that the node is *needed* for this cycle's decisions. Everything else
(gates and rules, the weekly reminder, sections, the soul, the code-owned blocks) is **pinned** and always
served. The package is `policy_router/`: config-free, local, no hosted model.

## How a cycle is routed

1. **Context.** The INDEX REGIME label, holdings, watchlist and quarantine (one "state" chunk), the EVENT
   CALENDAR block, and the cycle's summaries (one chunk per headline and per insights paragraph).
2. **Embeddings.** LM Studio's OpenAI-compatible `POST /v1/embeddings` on `127.0.0.1:1234`
   (`text-embedding-nomic-embed-text-v1.5`, query/document prefixes). One call per cycle; node texts come
   from an sqlite cache keyed by sha256(model + text). Hard budget: 5 s. Measured on the latest live
   cycle: about 1 s with a cold cache and 2 ms warm.
3. **Features** per (cycle, node): cosine to the context vector, max cosine to any headline / insights /
   event chunk, the deterministic route flags of `policy_graph/assembly.py` (regime, ticker, news,
   entities, trend, quarantine, recent), the logit of a Beta-smoothed prior of the node's historical
   needed-rate, node kind, diary age, and memory-row weight.
4. **Model.** L2 logistic regression fit by IRLS in numpy, class-weighted, with a prior correction so p
   stays calibrated.
5. **Optional LLM tier.** For nodes with p in 0.2–0.8, it asks a chat model on the same endpoint "Will this
   guideline be needed for this cycle's decisions?". P(yes) is read from the first token's logprobs, or
   from a constrained JSON `{"p": …}` when the server returns no logprobs, and averaged with the base p in
   logit space. The tier is auto-detected through `GET /v1/models`, has a hard budget of 15 s per cycle,
   and is skipped with one log line when no chat model is loaded. That is the case today, while the
   2×RTX 3090 host is offline.
6. **Selection.** Include every node with p ≥ tau_min. Then add nodes by descending p until the expected
   recall Σp(selected) / Σp(all) reaches the artifact's target. Memory rows are capped at
   `DAI_MEMORY_LT_LIMIT` (14).

## Modes (`DAI_POLICY_ROUTER`, default `shadow`)

| mode | what the Decider reads | what is logged |
|---|---|---|
| `off` | today's prompt | nothing |
| `shadow` | **exactly today's prompt** | every node's p, choice, and whether the prompt carried it |
| `active` | pinned nodes + the routable nodes kept. The memory rows are chosen from ALL active rows, at most 14. The excluded ids are listed in one tail line per block and accepted as citations | same, plus `served_in_prompt` reflects the router's choice |

`active` runs only when the artifact is **certified** for the configured recall target, routable kinds
and memory cap. Otherwise the cycle runs as shadow and the log says why. Every failure falls back to
today's prompt with one log line: no artifact, an embedding timeout, the endpoint down, a malformed
artifact, or an embedding-model mismatch. The router never touches decisions, so it can never block a
SELL.

## Label: what "needed" means

`needed(node, cycle)` is true when any of these holds:

- **explicit**: a decision of the cycle cited the id, or a considered/rejected setup did, once those
  carry citations;
- **similar**: the node's text is reflected in one of the cycle's decision or considered reasons, meaning
  max cosine(node, reason) ≥ θ. θ is the median cosine between explicitly cited guidelines and the
  reasons that cited them (0.724 on 750 pairs). In words: a reason reflects this node at least as strongly
  as a typical citation reflects its guideline;
- **ticker**: the node names a ticker the cycle decided on or considered.

Why not explicit citations alone? Memory rows had zero citations ever, because they were not citable, and
diary entries were never cited. A model trained only on citations would learn to drop all of them.

**Weakness.** Similarity cannot tell *use* from *redundancy*. A memory row that restates a pinned gate is
labeled needed whenever the gate is applied, although the gate already carries the content. A ticker
mention marks a node needed whenever its ticker is on the table. Both errors label more nodes as needed,
never fewer. The trainer therefore also evaluates a **marginal** variant (`--label marginal`): a reason
counts only when the node explains it at least as well as every pinned guideline. That removes the
redundancy error, but it can under-label a node that restates a gate with one decisive nuance.

## Training and certification

```
python -m policy_router.train --config-hash 9ea09b9as --db-url postgresql:///adobi [--recall-target 0.98]
```

The trainer reads the database read-only. It rebuilds each logged cycle from `policy_graph_runs`,
`policy_graph_hits`, `trade_decisions`, `summaries`, `momentum_snapshots`, `event_risk_snapshots` and
`trade_outcomes`, plus the materialized version directory. A `decider_inputs` table is used field by field
when it exists. The protocol:

- a **time split**: the oldest 70% of cycles train and the newest 30% are held out;
- settings chosen by **leave-one-week-out on the training cycles only**;
- **leave-one-week-out over all cycles** as a second opinion.

Priors are leak-free: each training cycle sees only earlier cycles, and held-out cycles use the frozen
training counts. The artifact is written with `certified = true` only if held-out recall ≥ target, and is
then refit on every cycle. Outputs go to `agents/decider/policy-router/<hash>/` (gitignored): `model.json`,
`eval.json` and `eval.md`.

## Measured on the live logs (2026-10-04, 101 cycles, 2026-09-03 → 2026-10-02)

Held out: the newest 30 cycles (2026-09-23 → 2026-10-02). Routable: diary entries + memory rows.

| label | held-out recall | today's prompt | best possible under the 14-row cap | chars/cycle router vs today | Brier (base-rate forecast) | LOWO recall | certified at 0.98 |
|---|---|---|---|---|---|---|---|
| plain (default) | **96.0%** (24 misses of 603) | 74.8% | 98.0% | 8,288 vs 7,587 (+9%) | 0.094 (0.233), AUC 0.93 | 97.6% | no |
| marginal | **97.4%** (2 misses of 76) | 90.8% | 100% | 5,854 vs 7,587 (−23%) | 0.062 (0.073), AUC 0.86 | 98.7% | no |

Reading these numbers:

- **The memory cap.** Under the plain label, 54.6% of active memory rows count as needed. Fourteen rows
  can hold at most 98.0% of them even with perfect ranking. At the same 14-row budget the router reaches
  93.3% memory-row recall against today's fixed sort at 64.7%.
- **Diary entries.** About 93% of them are "similar" to some reason, so the router keeps all of them:
  100% recall against 89.4% today, at a few hundred more characters.
- **What the misses are.** Plain-label misses are memory rows only. DA.ltm.7 (the IRDM chase mistake)
  accounts for 10 of the 24, and DA.ltm.21 (re-entry quarantine) for 5. The marginal label misses two
  diary entries once each.
- **Verdict.** Neither label clears 98% on the held-out cycles, so the default stays **shadow**. Shadow
  logs accumulate the cycles to retrain on. Once memory rows and rejections carry citations, the explicit
  part of the label stops being empty.
