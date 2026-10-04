"""Routable nodes: the policy graph's diary entries / lessons and decider_memory rows, as one shape.

`RouterNode` carries what the router needs from a guideline: its id and kind, the text the Decider
reads (and the router embeds), what it costs in the prompt (chars), its tickers and tags, and for
memory rows their weight. Built from `policy_graph.model.Node` objects — the version directory's
nodes and the `DA.ltm.<id>` overlay — or from decider_memory rows via `policy_graph.lessons`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Iterable, Optional

from policy_graph.assembly import DATE_RE, TICKER_RE

ROUTABLE_NODE_TYPES = {"entry": "entry", "ltm": "ltm", "lesson": "lesson"}
_LTM_ID_RE = re.compile(r"^DA\.ltm\.(\d+)$")


@dataclass
class RouterNode:
    node_id: str
    kind: str                                   # entry | ltm | lesson
    text: str                                   # what the Decider reads (and the router embeds)
    chars: int                                  # what it costs in the prompt
    tickers: frozenset = frozenset()
    tags: frozenset = frozenset()
    weight: float = 1.0                         # decider_memory weight (memory rows)
    date: Optional[datetime] = None             # diary entry date (from the id)
    created_at: Optional[datetime] = None       # memory row creation time
    field: str = ""
    node: object = None                         # the policy_graph Node (route flags)
    meta: dict = dc_field(default_factory=dict)

    @property
    def ltm_row_id(self) -> Optional[int]:
        m = _LTM_ID_RE.match(self.node_id)
        return int(m.group(1)) if m else None


def entry_date(node_id: str) -> Optional[datetime]:
    m = DATE_RE.search(node_id or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def node_tickers(node) -> set:
    """Tickers a guideline names: its curated `tickers` plus ticker-shaped tags (as assembly does)."""
    out = {str(t).upper() for t in (getattr(node, "tickers", None) or []) if t}
    for t in getattr(node, "tags", None) or []:
        s = str(t).upper().lstrip("#")
        if s and TICKER_RE.fullmatch(s):
            out.add(s)
    ex = getattr(node, "extra", None) or {}
    if ex.get("ticker"):
        out.add(str(ex["ticker"]).upper())
    return out


def _plain_tags(node) -> set:
    return {str(t).lower().lstrip("#") for t in (getattr(node, "tags", None) or [])
            if t and not TICKER_RE.fullmatch(str(t).upper().lstrip("#"))}


def _dt(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def from_graph_node(node) -> Optional[RouterNode]:
    """A RouterNode for a routable policy-graph node (entry / lesson / memory row), else None."""
    kind = ROUTABLE_NODE_TYPES.get(getattr(node, "node_type", ""))
    body = str(getattr(node, "body", "") or "")
    if kind is None or not body.strip():
        return None
    ex = getattr(node, "extra", None) or {}
    if kind == "ltm" and (ex.get("active") is False or not _LTM_ID_RE.match(str(node.id))):
        return None                             # inactive rows and the DA.ltm group node are not candidates
    if kind == "ltm":
        chars = len(body) + 1                   # one line of the LESSONS block
    else:
        chars = len(getattr(node, "sep_before", "") or "") + len(body) + len(getattr(node, "sep_after", "") or "\n")
    weight = float(ex.get("weight")) if ex.get("weight") is not None else 1.0
    return RouterNode(
        node_id=node.id, kind=kind, text=body.strip(), chars=int(chars),
        tickers=frozenset(node_tickers(node)), tags=frozenset(_plain_tags(node)), weight=weight,
        date=entry_date(node.id) if kind == "entry" else None, created_at=_dt(ex.get("row_created_at")),
        field=str(getattr(node, "field", "") or ""), node=node,
        meta={"title": getattr(node, "title", "") or node.id, "injected": ex.get("injected")},
    )


def version_nodes(version, kinds: Iterable = ("entry", "lesson", "ltm")) -> list:
    """Routable nodes of a materialized policy version (the LTM overlay included), document order."""
    kinds = set(kinds)
    out = []
    for n in sorted(version.nodes.values(), key=lambda x: (str(x.field or "~"), int(getattr(x, "order", 0) or 0), x.id)):
        rn = from_graph_node(n)
        if rn is not None and rn.kind in kinds:
            out.append(rn)
    return out


def ltm_row_nodes(rows: list) -> list:
    """RouterNodes for decider_memory rows (active only), built exactly as the graph's LTM overlay."""
    from policy_graph.lessons import ltm_nodes
    _sha, nodes = ltm_nodes([dict(r) for r in (rows or [])], injected_limit=0)
    out = []
    for n in nodes:
        rn = from_graph_node(n)
        if rn is not None:
            out.append(rn)
    return out


__all__ = ["RouterNode", "from_graph_node", "version_nodes", "ltm_row_nodes", "node_tickers", "entry_date"]
