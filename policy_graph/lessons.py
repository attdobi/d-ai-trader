"""decider_memory snapshot → DA.ltm.<id> nodes (read-only overlay).

Rows are passed in explicitly (service.py reads them; tests build dicts), each shaped like a
decider_memory row: id, content, active, weight, tags, ticker, kind, source, created_at,
updated_at. The body of every node is the exact line decider_memory.format_long_term_memory
prints for that row: "- [<kind>] (<TICKER>) <content>" — the trader is never imported.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from .model import Node

LTM_GROUP_ID = "DA.ltm"
LTM_GROUP_TITLE = "Long-term memory rows (decider_memory)"
DEFAULT_INJECTED_LIMIT = 14


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def format_memory_line(row: dict) -> str:
    """Byte-identical to one line of decider_memory.format_long_term_memory."""
    tk = f" ({row['ticker']})" if row.get("ticker") else ""
    kind = (row.get("kind") or "lesson")
    return f"- [{kind}]{tk} {row['content']}"


def _tags(row: dict) -> list:
    tags = row.get("tags")
    if tags is None:
        return []
    if isinstance(tags, str):
        s = tags.strip()
        if s.startswith("{") and s.endswith("}"):           # Postgres TEXT[] literal
            s = s[1:-1]
            return [t.strip().strip('"') for t in s.split(",") if t.strip()]
        if s.startswith("["):
            try:
                return [str(t) for t in json.loads(s)]
            except ValueError:
                pass
        return [t.strip() for t in s.split(",") if t.strip()]
    return [str(t) for t in tags]


def _sort_key(row: dict):
    """weight desc, created_at desc — the trader's get_relevant_memories order (minus the
    per-cycle ticker match, which the panel explains can displace rows)."""
    created = _iso(row.get("created_at")) or ""
    weight = float(row.get("weight") if row.get("weight") is not None else 1.0)
    return (-weight, _desc_str(created), int(row.get("id") or 0))


def _desc_str(s: str):
    # descending order for strings: negate each code point (ISO timestamps compare lexically)
    return tuple(-ord(c) for c in s)


def snapshot_sha(rows: list) -> str:
    """sha256[:12] over the sorted JSON of (id, content, active, weight, tags, ticker, kind, updated_at)."""
    items = sorted(
        [
            [
                int(r.get("id") or 0), r.get("content"), bool(r.get("active", True)),
                float(r.get("weight")) if r.get("weight") is not None else None,
                _tags(r), r.get("ticker"), r.get("kind"), _iso(r.get("updated_at")),
            ]
            for r in rows
        ],
        key=lambda x: x[0],
    )
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def ltm_group_node() -> Node:
    """The 'DA.ltm' group node (decompose_row normally creates it; offered here for overlay writers)."""
    return Node(
        id=LTM_GROUP_ID, agent="DeciderAgent", title=LTM_GROUP_TITLE, node_type="ltm", parent="DA.root",
        field=None, body="", polarity="evidence", polarity_source="override", owner="decider_memory",
        status="read-only", compiled="never", locked=True, provenance="decider_memory",
    )


def ltm_nodes(rows: list, *, injected_limit: int = DEFAULT_INJECTED_LIMIT) -> tuple:
    """(sha12, nodes) — one 'DA.ltm.<id>' node per row, ordered as the trader would rank them
    (weight desc, created_at desc); `injected: true` on the top `injected_limit` active rows."""
    rows = [dict(r) for r in (rows or [])]
    ordered = sorted(rows, key=_sort_key)
    injected_ids = set()
    for r in ordered:
        if len(injected_ids) >= injected_limit:
            break
        if bool(r.get("active", True)):
            injected_ids.add(int(r["id"]))
    nodes = []
    for order, r in enumerate(ordered):
        rid = int(r["id"])
        active = bool(r.get("active", True))
        ticker = (r.get("ticker") or "").upper() or None
        content = r.get("content") or ""
        title = content.strip().split("\n", 1)[0]
        if len(title) > 72:
            title = title[:69].rstrip() + "…"
        nodes.append(Node(
            id=f"{LTM_GROUP_ID}.{rid}",
            agent="DeciderAgent",
            title=title or f"decider_memory #{rid}",
            node_type="ltm",
            parent=LTM_GROUP_ID,
            field=None,
            body=format_memory_line(r),
            order=order,
            polarity="evidence",
            polarity_source="override",
            owner="decider_memory",
            status="active" if active else "inactive",
            compiled="never",
            locked=True,
            provenance=f"decider_memory#{rid}",
            tags=_tags(r),
            tickers=[ticker] if ticker else [],
            extra={
                "kind": r.get("kind") or "lesson",
                "source": r.get("source") or "feedback",
                "weight": float(r.get("weight")) if r.get("weight") is not None else 1.0,
                "ticker": ticker,
                "row_created_at": _iso(r.get("created_at")),
                "row_updated_at": _iso(r.get("updated_at")),
                "injected": rid in injected_ids,
                "active": active,
            },
        ))
    return snapshot_sha(rows), nodes
