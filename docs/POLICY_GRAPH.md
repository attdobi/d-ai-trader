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

## Phase 2 — the loop edits the graph (designed, not built)

1. **Proposals as guideline-file patches.** The generator returns at most 3 node files (RUSH clip),
   exactly one marked `primary`, each with `what / why / expected_effect / falsified_if` and the full
   file content. Locked nodes (Mission, Shared Principles, GROUND TRUTH, templates, code, memory rows,
   the weekly reminder) cannot be edited. `kind` is derived from the diff (a numeric threshold or a
   regime/kill/quarantine/extension/harvest change is `major`; whitespace/reorder is `minor`).
   Proposals persist in a `policy_graph_proposals` table and `proposals/<id>/` so they survive
   dashboard restarts.
2. **Critic on per-node diffs.** The critic receives one unified diff per guideline file and judges
   the diff, not the self-description; `is_substantive` comes from the diff.
3. **Per-guideline human approval** on the tab: file cards with diffs, approve checkboxes (the
   primary cannot be unchecked), proposed nodes drawn as ghosts on the graph.
4. **Accept = mint → compile → activate.** Copy the active version dir, overlay approved files,
   validate the graph, compile the five fields, run the existing guards, insert the `prompt_versions`
   row and activate through `prompt_manager.set_active_prompt_version` in one transaction, then rename
   the directory into place. Weekly reminder-only drift is rebased, not rejected.
5. **Weekly Thursday path** becomes "append the reminder node + memory entry, then compile", using the
   same string functions as today so bytes stay identical, and writing memory into the new row before
   activation (versions become immutable after creation).
6. **Citations and node health (2c).** The Decider output gains a `cited: [guideline ids]` list per
   decision; outcomes are joined back to the cited guidelines so each node shows "cited by N buys ·
   wins/losses · P&L" and the drafter gets RUSH-style `policy_blame`.

Two decisions are yours before Phase 2 ships: (a) accept a reviewed prompt change that relaxes the
Decider's "No extra keys" contract to carry `cited` ids; (b) make weekly versions immutable (memory
written into the new row before activation instead of updating the active row afterwards).
