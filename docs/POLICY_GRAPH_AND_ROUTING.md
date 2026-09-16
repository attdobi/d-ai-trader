---
title: "Policy Graph and Routing"
subtitle: "How d-ai-trader keeps its learnings as a knowledge graph and how the Decider reads it"
author: "d-ai-trader · written 2026-09-16 for reuse in RUSH"
---

# 1. The idea in one paragraph

The trading policy is text, not weights: each agent's prompt is a **soul** (identity), **strategy directives** (numbered gates) and a **memory** (lessons, patterns, mistakes, a dated diary). The loop rewrites that text from realized P&L. Every prompt version is also kept as a **knowledge graph**: one Markdown guideline per file plus an `edges.json`, in the RUSH layout, and the graph compiles back to the stored prompt byte for byte. The graph is therefore not a picture of the policy; it *is* the policy, with a version history, per-guideline evidence, and a record of which guideline drove which decision.

# 2. The graph on disk

```
agents/decider/policy-graph/
  baseline/v0/          the v0 policy every fresh checkout starts from        (git)
  latest/               copy of the ACTIVE version + its overlays              (git)
  <config-hash>/        this machine's history, one directory per version     (local)
    v31/                <id>.md guideline files + edges.json + manifest.json
    _code/<sha12>/      code-owned prompt blocks, content-addressed, read-only
    _ltm/<sha12>/       long-term memory rows as of that version, read-only
    _prior/             previous contents of a row that was rewritten in place
```

**Ids** are dotted and agent-prefixed: `DA.directives.strategy.priced_kill`, `DA.soul.risk_management`, `DA.memory.lessons.event_risk`, `DA.memory.log.2026_09_02_regime`, `DA.code.index_regime`, `DA.ltm.20`. The filename is the id plus `.md`; each file carries YAML front matter (agent, type, parent, field, order, owner, status, polarity, provenance, tags, tickers) and the guideline body.

**The fidelity contract ("same bytes").** The three evolving fields are partitioned into contiguous slices (`sep_before + body + sep_after`), so compiling a version is plain concatenation in `manifest.compile_order`, and `compile(decompose(row)) == row` for every historical version. Nothing half-faithful can land on disk: the store re-reads what it wrote and asserts equality before renaming the directory into place. The live trader never reads the files; it reads the database row, and the graph is derived beside it.

# 3. Three layers

| Layer | What it is | Node types | Editable by the loop |
|---|---|---|---|
| **Policy** | the `.md` guidelines compiled into the Decider's prompt: numbered **gates** (strategy directives), identity (soul), lessons / patterns / mistakes / diary and the weekly reminder (memory) | field, section, rule, lesson, entry, reminder, identity | yes: proposals, weekly loop |
| **Prompt scaffold** | the fixed prompt around the policy: the root, the system and user templates, the code-owned paragraphs the trader appends every cycle, the runtime-inputs note | root, template, code, data | no: code and templates |
| **Cycle context** | what the Decider sees per cycle, never policy: long-term memory rows, world events and market factors (regime, FOMC / CPI / jobs windows, earnings dates), ticker references | ltm, factor, ticker | no: rebuilt on every read |

The tab opens on the policy layer alone. A gate or lesson is shown as plain lines (label, then one sentence per line with the numbers emphasised) with the original text one click away, and every node starts with one sentence saying what it is to the Decider.

# 4. Edges

| On the tab | Types behind it | Meaning |
|---|---|---|
| part of | `subtype_of` | hierarchy: rule → section → field → root |
| feeds | `includes`, `constrains`, `enforced_by`, `triggers` | prompt assembly; a code block enforcing a rule; a world factor consumed by a rule |
| related | `related_to`, `overlaps`, `cites`, the RUSH seven | wiki-links and shared `#tags`; text overlap with a code or memory block; ticker mentions |

Edges are derived, never authored by hand, except the small code-to-rule map (`CONSTRAINS`) and the factor-to-rule map (`FACTOR_RULES`).

# 5. How learnings enter the graph

1. **Weekly loop (Thursday night).** The Feedback agent audits the closed trades from population diagnostics (regime split, entry extension, kill kind, re-entry churn, event windows, payoff) and writes a `Latest Feedback Reminder` section of ordered gates into the strategy directives plus lessons into the memory. Soul and memory are carried forward; the previous version stays immutable.
2. **Proposals (the loop edits the graph).** A proposal is a patch of at most three guideline files (`edit`, `add`, `remove`, exactly one `primary`) with what / why / expected effect / falsified-if. Flow: drafter (LLM) → validation and a dry-run round trip through the decomposer → critic (LLM, per file, trust-region doctrine) → human approval per guideline on the tab → apply: mint the next `prompt_versions` row, activate it through the audited switchboard, materialize the directory. Files never live in SQL; proposals do (`policy_graph_proposals`).
3. **Operator path.** A hand-authored proposal goes through the same validation, critic verdict and record (`policy_graph/operator.py: apply_hand_authored`), applied with the actor named; pure maintenance (ordering, a trimmed clause) uses `maintenance_version` and is labelled as such.
4. **Plain gates.** Every writer of rules is held to one shape: *"N. LABEL — IF one condition on a supplied field, with its number THEN one action. Otherwise next gate. Falsified if which number over how many trades proves it wrong."*, at most 240 characters, one condition per gate. A style lint flags long, multi-condition, parenthetical or unfalsified gates; the critic and the human both see the warnings.
5. **Citations.** Every decision carries `cited`: 1 to 4 guideline ids copied from an index the prompt prints. They are folded into the reason (` [cites: DA.…]`), stored with the trade, and become each guideline's realized record.

# 6. How the Decider reads it: the routing

Each cycle the Decider's soul, directives and memory are rebuilt from the active version's graph by a **deterministic query**, never a model call:

| Route | What it keeps |
|---|---|
| core | every numbered gate, every lesson, the section structure (the policy itself is never trimmed) |
| identity | the soul sections, verbatim |
| reminder | the weekly `Latest Feedback Reminder` |
| regime | a diary entry whose text names the current regime (RISK-ON / MIXED / RISK-OFF) |
| ticker / news / entities / trend | a diary entry that cites a ticker held, on the contrarian watchlist, in the Summarizers' headlines, among the extracted companies, or in the momentum recap |
| quarantine | re-entry guidance while the quarantine line is non-empty |
| recent | a diary entry dated within 30 days |
| tag | one hop over shared `#tags` from an entry served for one of the reasons above |
| code / ltm | the code-owned blocks and the injected memory rows (recorded so utilization is honest) |

Everything else (older diary entries) is dropped from the rendering and listed by id in one line so it stays citable. Each served guideline is rendered with its record: ` ⟨id · cited 7d/30d/90d: 3/12/20 · win 58% n=12⟩`, and the prompt tells the Decider to weigh a rule by that record rather than its wording. Every cycle logs what was served (with its route) and what was cited (`policy_graph_hits`, `policy_graph_runs`).

**Measured on Decider v28 (46 cycles):** 38–39 guidelines served, 0–1 dropped; 17.9k characters of policy, about 4.5k tokens, served whole. Sixteen policy guidelines were served every cycle and cited never; PRICED KILL, REGIME GATE and HARVEST carried most decisions.

**Why no routing agent.** The policy fits in the prompt with room to spare, so a model choosing which guidelines to show would add cost, latency and non-determinism to select among ~36 items that already fit, and would make the served set unreproducible. The lever is the opposite one: prune what is never cited, through proposals, on evidence. A router or a set of expert sub-policies becomes worth it only if the diary or per-ticker playbooks outgrow the prompt.

# 7. Decision paths and world factors

A decision's path is *context → route that served a guideline → guideline cited → action → outcome*. The tab draws it as a three-column flow (routes or world factors → guidelines → buy / hold / sell), lists guidelines cited but never served (the query missed them) and served but never cited (dead weight), and scores each guideline over the closed trades that cited it: win rate, P&L, and what was co-cited on its winners and its losers.

**World factors** are read-time nodes rebuilt from the run log: the regime the trader read, the FOMC / CPI / jobs windows (reconstructed for any past cycle from the event calendar), operator events, and holdings or candidates reporting earnings inside the hold window. Each points at the rules that consume it and at the guidelines the Decider actually cited while it was active, and the Factor quality table shows the trades entered under it. They never touch the materialized directories.

# 8. Reusing it in RUSH

- **Port the layout, not the trader.** `<id>.md` with front matter + `edges.json` + `manifest.json` per version; content-addressed overlay folders; a `latest/` copy in git; `baseline/v0` for fresh checkouts.
- **Keep the same-bytes contract.** Decompose into contiguous slices; compile by concatenation; verify the round trip before writing. It is what lets a graph be the source of truth for a prompt.
- **Give every node a layer and a plain kind.** Policy / scaffold / context, and gate / lesson / diary entry / memory row / factor. Show the policy layer by default.
- **Keep routing deterministic and logged.** Routes as named reasons, a served row per guideline per cycle, a cited row per decision. Utilization (served versus cited) is the pruning signal.
- **Gates in the plain shape,** one condition each, with a falsification metric; lint them; let the critic see the warnings.
- **Proposals as patches of at most three files** with one primary; human approval per file; the applied files become the next version, never the SQL.

# 9. Pointers

- Package: `policy_graph/` (`decompose.py`, `compile.py`, `store.py`, `service.py`, `assembly.py`, `citations.py`, `proposals.py`, `operator.py`, `paths.py`, `factors.py`, `prompts.py`, `code_blocks.py`).
- Tab: `/policy-graph`; API: `/api/policy-graph/{agents, versions, graph, node, diff, compiled, bundle, file, paths, proposals}`.
- CLI: `python -m policy_graph.backfill --config-hash <hash> [--verify-only]`, `--baseline` to regenerate the committed v0.
- Docs: `docs/POLICY_GRAPH.md` (this document is the short form).
