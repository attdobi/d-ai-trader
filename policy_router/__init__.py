"""Jev-like policy router for the Decider: a typed decision per routable guideline.

For every routable node of a cycle (diary entries and long-term memory rows by default; lessons
opt in) the router returns `{node_id, p, choice: include|exclude, confidence}` where `p` is a
calibrated probability that the node is *needed* for this cycle's decisions. The served subgraph
is every pinned node (gates, rules, reminder, sections, soul, code-owned blocks) plus the routable
nodes the selection keeps so that the expected recall of needed nodes stays at a target while
fewer characters are served. It is a non-generative decision model, built locally:

    embed.py     OpenAI-compatible embeddings (LM Studio on 127.0.0.1:1234) with an on-disk cache
                 and a hard wall-clock budget
    features.py  per (cycle, node) features: cosine to the cycle context, max cosine to the headline
                 chunks, the deterministic route flags of policy_graph.assembly, a Beta-smoothed
                 prior of the node's historical needed-rate, node kind, diary age, memory weight
    model.py     L2-regularized logistic regression (numpy IRLS) with class weighting and a prior
                 correction so p stays calibrated; reliability bins and Brier score
    select.py    the typed decision and the recall-targeted subgraph selection
    llm_tier.py  optional escalation for uncertain nodes: a yes/no question to a chat model on the
                 same endpoint, P(yes) read from logprobs (or a constrained JSON {"p": …})
    labels.py    what "needed" means (see below)
    dataset.py   the labeled dataset rebuilt from the logs (read-only)
    train.py     `python -m policy_router.train --config-hash <hash>`: time split + leave-one-week-out
                 evaluation, settings that meet the recall target on held-out cycles, artifact
    runtime.py   one cycle at decision time: off | shadow | active, every failure → today's prompt
    log.py       policy_router_decisions / policy_router_runs (one row per node, one per run)
    panel.py     the Policy Graph tab's Router panel

LABEL — needed(node, cycle) is true when any of:
  * explicit: a decision (or, once logged, a considered/rejected setup) of the cycle cited the id;
  * implicit (semantic): the node text is reflected in one of the cycle's decision or considered
    reasons — max cosine(node, reason) >= theta, with theta set from the data as a quantile of the
    cosine between explicitly cited guidelines and the reasons that cited them ("a reason reflects
    this node at least as strongly as a typical explicit citation reflects its guideline");
  * implicit (ticker): the node names a ticker the cycle decided on or considered.
A router trained on explicit citations alone would learn to drop every memory row and diary entry
(they had zero citations: memory rows were not citable, diary entries were never cited), which is
degenerate. WEAKNESS of the implicit label: cosine similarity cannot tell *use* from *redundancy* —
a memory row that restates a pinned gate is labeled needed whenever the gate is applied, although
the pinned gate already carries the content; and a ticker mention marks a node needed whenever the
ticker is on the table even if its lesson was irrelevant. Both errors push toward serving more,
never less, so recall measured against this label is conservative for safety and pessimistic for
savings.

The package never imports `config` and never reads the process environment: settings, the engine and the HTTP
transport are passed in.
"""
from __future__ import annotations

ROUTABLE_KINDS = ("entry", "ltm", "lesson")
DEFAULT_ROUTABLE = ("entry", "ltm")
AGENT_DIR = "decider"

__all__ = ["ROUTABLE_KINDS", "DEFAULT_ROUTABLE", "AGENT_DIR"]
