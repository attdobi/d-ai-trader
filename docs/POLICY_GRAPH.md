# Policy Graph

Each agent's prompt (Summarizer, Decider, Feedback) is now also a **versioned knowledge graph**:
a directory of Markdown guideline files plus `edges.json`, one directory per prompt version, in the
RUSH layout (see `~/RUSH/policy-graph/`). The dashboard's **Policy Graph** tab renders it as a
force-directed graph with a version timeline, so you can watch the policy evolve through the
reinforcement-learning loop instead of reading five-field diffs.

```
agents/decider/policy-graph/9ea09b9as/
  v0/ … v21/           <id>.md guideline files + edges.json + manifest.json  (one dir per prompt version)
  _code/<sha12>/       code-owned prompt blocks (decider_agent.py etc.), content-addressed, read-only
  _ltm/<sha12>/        decider_memory rows as of that version, content-addressed, read-only
  _prior/v<N>-<sha8>/  previous contents of a version whose database row was rewritten in place
  .lock                inter-process lock (trader + dashboard worker may both write)
```

Node ids are dotted and agent-prefixed (`DA.`, `SA.`, `FA.`), filename == id + `.md`, one root per
graph. Examples from Decider v21: `DA.directives.strategy.priced_kill`, `DA.soul.core_philosophy`,
`DA.memory.lessons.extension_chase`, `DA.memory.log.2026_09_02_regime`, `DA.code.confirmation_policy`,
`DA.ltm.20`.

## The fidelity contract ("same bytes")

The three evolving fields (`strategy_directives`, `soul`, `memory`) are **partitioned** into
contiguous slices (`sep_before + body + sep_after`); compiling a version is plain concatenation in
`manifest.compile_order`. Therefore `compile(decompose(row)) == row` byte-for-byte. This holds for
every historical row (49 versions × 5 fields, checked by `python -m policy_graph.backfill --verify-only`
and by `tests/test_policy_graph_roundtrip.py`). The two templates (`system_prompt`,
`user_prompt_template`) are single verbatim nodes. Nothing half-faithful can land on disk: the store
re-reads what it wrote and asserts equality before renaming the directory into place.

Because the graph compiles back to the exact prompt text, the graph *is* the policy. Phase 1 keeps
the live trader untouched: the runtime still reads `prompt_versions`; the graph is derived beside it.

## What the graph shows

- **Stored guidelines** (owner `db`): the text in the `prompt_versions` row, split into sections,
  numbered rules, tagged lessons and dated log entries.
- **Inherited defaults** (owner `default-file`, hollow nodes): when a row's soul/memory column is
  empty the runtime falls back to `agents/<dir>/SOUL.default.md` / `MEMORY.default.md`; the graph shows
  the git blob as of the row's `created_at`, labelled as inherited, never claiming the database held it.
- **Code-owned blocks** (owner `code`, dashed orange ring): the seven paragraphs `decider_agent.py`
  appends every cycle, the CROWD-FADE / CASH PLAYBOOK conditionals, the screener's INDEX REGIME and
  WATCHLIST headers, the LESSONS header. These are verbatim copies guarded by an `ast` drift test
  (`tests/test_policy_graph_code_blocks.py`) so a code edit fails one test, never the read path.
- **Long-term memory rows** (owner `decider_memory`, dotted): the `decider_memory` table rows the
  Decider retrieves each cycle, snapshotted per version.
- **Edges**: `subtype_of` (hierarchy), `includes` (runtime assembly), `related_to` (`[[wiki-links]]`
  and shared `#tags`), `cites` (tickers), `overlaps` (text similarity between a guideline and a
  code/memory block), `constrains` (code block → the rules it enforces).

Polarity colours: hard gate (red), action (green), caution (yellow), identity/principle (purple),
evidence/lessons (cyan), structure (grey).

## Using it

- Tab: `/policy-graph`. Agent switcher, version select + Prev/Next, timeline strip with actor
  (seed / weekly loop / human / Claude Code), critic and human verdicts, realized win-rate delta,
  hollow chips for reminder-only weekly versions, dotted ghost chips for rejected candidates.
- Click a guideline: rendered Markdown, provenance sentence, "what changed vs previous version"
  unified diff, history across versions, "also appears in" overlaps, link to the source file.
- Links: compiled prompt (byte-exact stored render), "as the model runs it" (runtime assembly
  preview), the RUSH-style `.md` bundle.
- API: `/api/policy-graph/{agents,versions,graph,node,diff,compiled,bundle,file,rebuild}`.
- CLI: `./dai/bin/python -m policy_graph.backfill --config-hash 9ea09b9as [--verify-only] [--force]`.
- The tab materializes missing or stale versions on read (the weekly loop mutates the active row's
  memory in place; the previous files move to `_prior/` and the chip shows `↻`).

Rules for the package: stdlib only, never imports `config`, never reads `os.environ`; `config_hash`
and `repo_root` are explicit parameters. Tests are DB-free (`tests/test_policy_graph_*.py`).

## Phase 2 — the loop edits the graph

Built 2026-09-03 (`policy_graph/proposals.py`, the **Proposed changes** card on the tab).

**Where things live.** Guideline files stay on disk under git (`agents/<dir>/policy-graph/…`), the
compiled prompt stays in `prompt_versions` (the trader reads only that), and proposals are the
one new SQL table, `policy_graph_proposals` (JSON as text; `init_database.py` creates it, the
module also creates it lazily). Proposal files are never written to SQL: when a proposal is applied
the compiled row is inserted and the version directory is rebuilt from it by the same store as
every historical version, so the graph remains a byte-exact mirror of the database.

1. **Proposals are guideline-file patches.** `POST /api/policy-graph/proposals {agent_type, focus}`
   starts a background draft against the active version. The drafter (PromptEvolutionAgent's
   model, `policy_graph/prompts.py: DRAFTER_SYSTEM`) sees every editable guideline with its id,
   the locked ids, the code-owned blocks and memory rows as read-only context, the population
   diagnostics, trade evidence, past verdicts and past proposals, and returns at most 3 files —
   `edit` / `add` / `remove`, exactly one `primary`, each with what / why / expected_effect /
   falsified_if. Locked nodes (root, templates, code, memory rows, GROUND TRUTH, Mission, Shared
   Principles) cannot be touched; only strategy directives, soul and memory guidelines can.
2. **Validation is a dry run of the fidelity contract.** The patch is applied to the node sequence
   of the base version (sep_before + body + sep_after), compiled to text, and decomposed again
   with the standard builder; it is accepted only when every edited or added guideline is still
   exactly one file after the round trip. Failures come back in plain language ("merged into its
   neighbour — match the sibling format", "splits into several — remove the heading") and the
   drafter gets one retry with that message. Added guidelines receive the id the builder would
   give them (`DA.directives.strategy.liquidity`, `DA.memory.log.2026_09_03_kill_distance`).
   `kind` (major / minor) is derived from the diff in code, never from the model's description.
3. **Critic on per-file diffs.** The critic (same doctrine as the Prompt Lab gate,
   `CRITIC_DOCTRINE`, shared from `policy_graph/prompts.py`) judges each file's unified diff and
   returns per-file verdicts plus the overall trust-region verdict. Wording-only patches are
   auto-rejected without a model call. A `prompt_change_reviews` row is written at critic time so
   the scorecard, the timeline glyphs and the RLHF concordance label keep working.
4. **Per-guideline human approval on the tab.** Proposals awaiting review show file cards with
   the diff, the drafter's claims and the critic's verdict; every supporting file has a checkbox,
   the primary cannot be unchecked. Proposed additions appear as dotted green ghost nodes on the
   graph, edited guidelines get a dotted ring, removals a red one; clicking one shows the proposed
   diff in the details panel.
5. **Apply = mint → activate → materialize.** `POST …/proposals/<id>/apply {approved: [ids]}`
   re-applies the approved files on the active version, inserts the `prompt_versions` row
   (`created_by = policy_graph`, description names the proposal), activates it through
   `prompt_manager.set_active_prompt_version` in the same transaction (`action = apply_proposal`),
   records the human verdict on the review row, then materializes the directory. If the active
   version moved since the draft (the weekly loop appended a reminder), the proposal is rebased
   automatically as long as the guidelines it touches are unchanged; otherwise it reports a
   conflict and asks for a fresh draft.

6. **Weekly versions are immutable.** The Thursday path computes the new memory text first and
   writes it into the new `prompt_versions` row together with the reminder section, then
   activates it (`feedback_agent._next_memory_text`). No row is rewritten after creation, so a
   version's guideline files never move to `_prior/` again; weekly versions are their own chips
   on the timeline.
7. **Citations and per-guideline health.** Decider v22 relaxed the output contract: each decision
   may carry `"cited": [guideline ids]`. The trader appends a `GUIDELINE INDEX (id — title)` of the
   active version's citable guidelines (rules, lessons, log entries, sections, and the code-owned
   blocks that fire) to every prompt (`decider_agent._guideline_index_text`, code-owned block
   `DA.code.guideline_citations`) and folds the returned ids into the reason as a trailing
   ` [cites: DA.…, DA.…]` (`policy_graph/citations.py`). The suffix travels with the reason into
   `trade_decisions`, `holdings` and `trade_outcomes.original_reason`, so the Trades tab shows the
   cited guidelines as an expandable chip row linking to the graph, and a guideline's panel shows
   "Cited by N decisions · M closed trades · win rate · P&L" (`citation_health`).

## Baseline for fresh checkouts

`agents/<dir>/policy-graph/baseline/v0/` is committed: the v0 policy of every agent decomposed
from `initialize_prompts.DEFAULT_PROMPTS` (templates, directives, `SOUL.default.md`,
`MEMORY.default.md`) under the pseudo config hash `baseline`, with volatile manifest keys
scrubbed so it is byte-stable. Regenerate it after editing the defaults with
`./dai/bin/python -m policy_graph.backfill --baseline`; `tests/test_policy_graph_baseline.py`
fails when it drifts. `init_database.py` also writes the same v0 under the machine's own config
hash, so a fresh checkout has its graph on disk from the first run. Personal evolution (v1…)
under a machine's config hash is not needed to start; this repository happens to carry the
author's `9ea09b9as` history as an example.
