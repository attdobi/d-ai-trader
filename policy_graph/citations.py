"""Guideline citations — which guidelines drove a decision (Phase 2, step 6).

The Decider may return `"cited": ["DA.directives.strategy.priced_kill", ...]` on each decision.
The trader folds that list into the decision's `reason` as a trailing ` [cites: id, id]` suffix
(`append_cites`), so nothing downstream changes shape: `trade_decisions.data[*].reason`,
`holdings.reason` and `trade_outcomes.original_reason` all carry the citation with the text.
`parse_cites` / `strip_cites` read it back; `guideline_index` renders the id list the Decider is
shown; `citation_health` joins decisions and closed trades back to one guideline id.

stdlib + `sqlalchemy.text`; never imports config; config_hash is explicit.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from sqlalchemy import text

from .model import COMPILED_FIELDS, ID_RE, Version

CITE_RE = re.compile(r"\s*\[cites?:\s*([^\]]*)\]\s*$", re.I)
MAX_CITES = 6
CITABLE_TYPES = ("section", "rule", "lesson", "entry", "reminder", "identity", "note", "code")
SYNCED_REASON = "Schwab synced position"


# ----------------------------------------------------------------------------- reason suffix
def parse_cites(reason) -> list:
    """Guideline ids cited in a reason (empty when none)."""
    m = CITE_RE.search(str(reason or ""))
    if not m:
        return []
    return normalize_ids(re.split(r"[,\s]+", m.group(1)))


def strip_cites(reason) -> str:
    return CITE_RE.sub("", str(reason or "")).rstrip()


def split_cites(reason) -> tuple:
    """(reason without the suffix, [ids])."""
    return strip_cites(reason), parse_cites(reason)


def append_cites(reason, ids: Iterable) -> str:
    """Reason text with ` [cites: …]` appended (replacing an existing suffix; unchanged when no ids)."""
    base = strip_cites(reason)
    clean = normalize_ids(ids)
    if not clean:
        return base
    return f"{base} [cites: {', '.join(clean)}]".strip()


def normalize_ids(raw, known: Optional[Iterable] = None) -> list:
    """Valid, de-duplicated guideline ids (prefix upper-cased, rest lower-cased), at most MAX_CITES,
    restricted to `known` when given."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    known_set = set(known) if known is not None else None
    out: list = []
    for item in raw:
        s = str(item or "").strip().strip("[]\"'`")
        if not s:
            continue
        head, _, tail = s.partition(".")
        s = f"{head.upper()}.{tail.lower()}" if tail else s.upper()
        if not ID_RE.match(s):
            continue
        if known_set is not None and s not in known_set:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= MAX_CITES:
            break
    return out


def fold_into_decisions(decisions, known: Optional[Iterable] = None) -> list:
    """Move each decision's `cited` list into its reason suffix (in place). Returns the ids used."""
    used: list = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        raw = d.pop("cited", None)
        if raw is None:
            raw = d.pop("cites", None)
        ids = normalize_ids(raw, known)
        if not ids:
            continue
        d["reason"] = append_cites(d.get("reason") or "", ids)
        used.extend(i for i in ids if i not in used)
    return used


# ----------------------------------------------------------------------------- what the Decider sees
def citable_nodes(version: Version) -> list:
    """[(id, title)] of the guidelines a decision may cite: stored / inherited guidelines of the
    three evolving fields (sections and their rules, lessons, log entries) plus the code-owned
    blocks that fire for this version; in compile order, code blocks last."""
    out = []
    order = version.manifest.get("compile_order") or {}
    fields_meta = version.manifest.get("fields") or {}
    for f in COMPILED_FIELDS:
        ids = list(order.get(f) or [])
        if (fields_meta.get(f) or {}).get("inherited"):
            ids = [n.id for n in sorted((x for x in version.nodes.values() if x.field == f and x.owner == "default-file"),
                                        key=lambda n: (n.order, n.id))]
        for i in ids:
            n = version.nodes.get(i)
            if n is None or n.node_type not in CITABLE_TYPES or not (n.body or "").strip():
                continue
            out.append((n.id, n.title or n.id))
    fires = (version.manifest.get("code") or {}).get("fires") or {}
    code = [n for n in version.nodes.values() if n.owner == "code" and n.node_type == "code"
            and fires.get(n.id, n.extra.get("fires", True)) and (n.body or "").strip()]
    for n in sorted(code, key=lambda n: (n.order, n.id)):
        out.append((n.id, n.title or n.id))
    return out


def guideline_index(version: Version) -> str:
    """One line per citable guideline: `id — title`."""
    return "\n".join(f"{i} — {t}" for i, t in citable_nodes(version))


# ----------------------------------------------------------------------------- health
def _decision_rows(engine, config_hash: str) -> list:
    """(timestamp, decision dict) for every stored decision whose reason carries a citation."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT timestamp, data FROM trade_decisions
            WHERE config_hash = :h AND CAST(data AS TEXT) LIKE '%[cites:%'
            ORDER BY timestamp DESC
        """), {"h": config_hash}).fetchall()
    out = []
    for r in rows:
        data = r[1]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if isinstance(data, dict):
            data = data.get("decisions") or []
        for d in data or []:
            if isinstance(d, dict) and d.get("action") and "[cites" in str(d.get("reason") or ""):
                out.append((r[0], d))
    return out


def citation_health(engine, config_hash: str, node_id: str, *, recent: int = 8) -> dict:
    """How one guideline has been used: decisions that cited it and the closed trades whose buy
    reason cited it (`trade_outcomes.original_reason`)."""
    decisions = [(ts, d) for ts, d in _decision_rows(engine, config_hash) if node_id in parse_cites(d.get("reason"))]
    by_action: dict = {}
    for _ts, d in decisions:
        a = str(d.get("action") or "").lower()
        by_action[a] = by_action.get(a, 0) + 1
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, original_reason, sell_reason
            FROM trade_outcomes
            WHERE config_hash = :h AND original_reason LIKE '%[cites:%' AND original_reason NOT LIKE :synced
            ORDER BY sell_timestamp DESC
        """), {"h": config_hash, "synced": f"%{SYNCED_REASON}%"}).fetchall()
    closed = [r for r in rows if node_id in parse_cites(r[4])]
    wins = sum(1 for r in closed if (r[2] or 0) > 0)
    pnl = float(sum(float(r[3] or 0) for r in closed))
    pct = [float(r[2]) for r in closed if r[2] is not None]
    return {
        "node_id": node_id,
        "decisions": len(decisions), "by_action": by_action,
        "closed": len(closed), "wins": wins, "losses": len(closed) - wins,
        "win_rate": (wins / len(closed)) if closed else None,
        "avg_gain_pct": (sum(pct) / len(pct)) if pct else None,
        "pnl": pnl,
        "recent_decisions": [{"timestamp": (ts.isoformat() if hasattr(ts, "isoformat") else str(ts)),
                              "ticker": d.get("ticker"), "action": d.get("action")} for ts, d in decisions[:recent]],
        "recent_closed": [{"ticker": r[0], "sell_timestamp": (r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1])),
                           "gain_pct": r[2], "gain_amount": r[3]} for r in closed[:recent]],
    }


__all__ = ["CITE_RE", "MAX_CITES", "parse_cites", "strip_cites", "split_cites", "append_cites", "normalize_ids",
           "fold_into_decisions", "citable_nodes", "guideline_index", "citation_health"]
