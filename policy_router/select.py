"""The typed decision: per routable node {node_id, p, choice: include|exclude, confidence}, and the subgraph.

Selection over the routable nodes of one cycle (pinned nodes are always included):
  1. include every node with p >= tau_min;
  2. then add nodes by descending p until the EXPECTED recall Σp(selected) / Σp(all) >= recall_target;
  3. never keep fewer than `min_per_kind[kind]` nodes of a kind (highest p first);
  4. never keep more than `max_per_kind[kind]` (an upper bound — e.g. DAI_MEMORY_LT_LIMIT for memory
     rows); when a cap binds, the expected recall reported is the one actually reached.
confidence = |p - 0.5| * 2 (0 = a coin flip, 1 = certain either way).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from typing import Iterable, Optional


@dataclass
class NodeDecision:
    node_id: str
    kind: str
    p: float
    choice: str                      # include | exclude
    confidence: float
    chars: int = 0
    pinned: bool = False
    why: str = ""                    # pinned | tau | recall | min_kind | cap | below_target
    p_base: Optional[float] = None   # before the LLM tier (None when the tier did not touch it)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["p"] = round(float(self.p), 6)
        d["confidence"] = round(float(self.confidence), 6)
        return d


@dataclass
class Selection:
    decisions: list                  # [NodeDecision] routable nodes, by descending p (pinned ones first)
    expected_recall: float
    tau_min: float
    recall_target: float
    capped: dict = dc_field(default_factory=dict)      # kind -> nodes dropped by the cap

    @property
    def included(self) -> list:
        return [d for d in self.decisions if d.choice == "include"]

    @property
    def excluded(self) -> list:
        return [d for d in self.decisions if d.choice == "exclude"]

    @property
    def include_ids(self) -> set:
        return {d.node_id for d in self.included}

    @property
    def chars_selected(self) -> int:
        return int(sum(d.chars for d in self.included if not d.pinned))

    @property
    def chars_routable(self) -> int:
        return int(sum(d.chars for d in self.decisions if not d.pinned))


def confidence_of(p: float) -> float:
    return abs(float(p) - 0.5) * 2.0


def select_subgraph(items: Iterable, *, pinned_ids: Iterable = (), tau_min: float = 0.5, recall_target: float = 0.98,
                    min_per_kind: Optional[dict] = None, max_per_kind: Optional[dict] = None) -> Selection:
    """`items` = [(node_id, kind, p, chars)] or dicts with those keys."""
    rows = []
    for it in items:
        if isinstance(it, dict):
            rows.append((str(it["node_id"]), str(it.get("kind") or ""), float(it.get("p") or 0.0), int(it.get("chars") or 0)))
        else:
            nid, kind, p, chars = (list(it) + [0])[:4]
            rows.append((str(nid), str(kind or ""), float(p or 0.0), int(chars or 0)))
    pinned = set(pinned_ids or ())
    rows.sort(key=lambda r: (-r[2], r[0]))
    pinned_rows = [r for r in rows if r[0] in pinned]
    routable = [r for r in rows if r[0] not in pinned]
    total = sum(max(r[2], 0.0) for r in routable)
    chosen: dict = {}

    def mass() -> float:
        return sum(max(r[2], 0.0) for r in routable if r[0] in chosen)

    for r in routable:                                   # 1. confident includes
        if r[2] >= tau_min:
            chosen[r[0]] = "tau"
    for r in routable:                                   # 2. expected recall
        if total <= 0 or mass() / total >= recall_target - 1e-12:
            break
        if r[0] not in chosen:
            chosen[r[0]] = "recall"
    for kind, k in (min_per_kind or {}).items():          # 3. floors per kind
        have = sum(1 for r in routable if r[0] in chosen and r[1] == kind)
        for r in routable:
            if have >= int(k):
                break
            if r[1] == kind and r[0] not in chosen:
                chosen[r[0]] = "min_kind"
                have += 1
    capped: dict = {}
    for kind, k in (max_per_kind or {}).items():          # 4. caps (upper bound wins)
        if k is None:
            continue
        kept = 0
        for r in routable:
            if r[1] != kind or r[0] not in chosen:
                continue
            kept += 1
            if kept > int(k):
                del chosen[r[0]]
                capped.setdefault(kind, []).append(r[0])
    decisions = [NodeDecision(node_id=r[0], kind=r[1], p=r[2], choice="include", confidence=confidence_of(r[2]),
                              chars=r[3], pinned=True, why="pinned") for r in pinned_rows]
    cap_ids = {i for ids in capped.values() for i in ids}
    for r in routable:
        inc = r[0] in chosen
        why = chosen.get(r[0]) if inc else ("cap" if r[0] in cap_ids else "below_target")
        decisions.append(NodeDecision(node_id=r[0], kind=r[1], p=r[2], choice="include" if inc else "exclude",
                                      confidence=confidence_of(r[2]), chars=r[3], why=why))
    exp = (mass() / total) if total > 0 else 1.0
    return Selection(decisions=decisions, expected_recall=float(exp), tau_min=float(tau_min),
                     recall_target=float(recall_target), capped=capped)


__all__ = ["NodeDecision", "Selection", "select_subgraph", "confidence_of"]
