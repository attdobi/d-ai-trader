"""Cross-version matching and diffs (spec section 9).

diff_versions(prev, cur) matches the db + inherited nodes of two versions:
  1. exact id, then a secondary key that ignores `_`/`-` in the last id segment
     (`reentry_quarantine` == `re_entry_quarantine`);
  2. rename detection among the leftovers, same field + same depth, greedy best pair by
     difflib ratio on normalised bodies (>= RENAME_RATIO);
  3. the rest is added / removed;
  4. a field whose owner flipped inherited <-> stored is reported in `source_changed` and its
     nodes carry change 'source_changed' instead of added/changed.

node_unified_diff renders a unified diff (lineterm=""), node_history follows a node through
every version along rename chains, version_kind classifies a version for the timeline chips.
stdlib only.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field as dc_field
from typing import Optional

from .model import AGENT_PREFIX, COMPILED_FIELDS, FIELDS, Node, Version, actor_kind

RENAME_RATIO = 0.6
DIFF_OWNERS = {"db", "default-file"}          # code/ltm/runtime/ticker/concept/generated are excluded
CHANGES = ("added", "removed", "changed", "same", "whitespace", "renamed", "source_changed")

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_NUMBER_RE = re.compile(r"^\s*\d+\.\s+")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_DATE_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*")
_BOLD_TAG_RE = re.compile(r"^\s*\*\*#?[^*]*\*\*\s*[—–:-]?\s*")
_WS_RE = re.compile(r"\s+")


# ----------------------------------------------------------------------------- shapes
@dataclass
class NodeChange:
    id: str
    change: str                              # one of CHANGES
    field: Optional[str] = None
    node_type: str = ""
    title: str = ""
    prev_id: Optional[str] = None            # id of the matched node in prev (renamed_from when renamed)
    cur_id: Optional[str] = None
    similarity: Optional[float] = None
    prev_sha256: Optional[str] = None
    cur_sha256: Optional[str] = None
    body_changed: bool = False

    @property
    def renamed_from(self) -> Optional[str]:
        return self.prev_id if self.change == "renamed" else None


@dataclass
class VersionDiff:
    added: list = dc_field(default_factory=list)
    removed: list = dc_field(default_factory=list)
    changed: list = dc_field(default_factory=list)
    renamed: list = dc_field(default_factory=list)          # [(old_id, new_id, ratio)]
    same: list = dc_field(default_factory=list)
    whitespace_only: list = dc_field(default_factory=list)
    source_changed: list = dc_field(default_factory=list)   # fields
    per_node: dict = dc_field(default_factory=dict)         # id -> NodeChange (cur ids; removed prev ids too)

    def summary(self) -> dict:
        return {"added": len(self.added), "changed": len(self.changed), "removed": len(self.removed),
                "renamed": len(self.renamed), "whitespace": len(self.whitespace_only),
                "source_changed": list(self.source_changed)}


# ----------------------------------------------------------------------------- helpers
def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def loose_key(node_id: str) -> str:
    """Secondary match key: the id with `_`/`-` removed from the last segment."""
    head, _, last = node_id.rpartition(".")
    return f"{head}.{re.sub(r'[_-]', '', last.lower())}" if head else re.sub(r"[_-]", "", node_id.lower())


def ws_collapsed(text: str) -> str:
    return " ".join((text or "").split())


def norm_body(text: str) -> str:
    """Rename-detection normalisation: drop heading/number/date/bullet markers at line starts,
    lowercase, digits -> '#', collapse whitespace."""
    lines = []
    for line in (text or "").splitlines():
        line = _HEADING_RE.sub("", line)
        line = _DATE_RE.sub("", line)
        line = _NUMBER_RE.sub("", line)
        line = _BULLET_RE.sub("", line)
        line = _BOLD_TAG_RE.sub("", line)
        lines.append(line)
    s = " ".join(lines).lower()
    s = re.sub(r"\d", "#", s)
    return _WS_RE.sub(" ", s).strip()


def similarity(a: str, b: str) -> float:
    na, nb = norm_body(a), norm_body(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


def diffable_nodes(version: Optional[Version]) -> dict:
    if version is None:
        return {}
    return {i: n for i, n in version.nodes.items() if n.owner in DIFF_OWNERS}


def _field_inherited(version: Optional[Version], field: str) -> Optional[bool]:
    if version is None:
        return None
    meta = (version.manifest.get("fields") or {}).get(field)
    if meta is None:
        return None
    return bool(meta.get("inherited"))


def _change_for_pair(prev_node: Node, cur_node: Node) -> str:
    if prev_node.body == cur_node.body:
        return "same"
    if ws_collapsed(prev_node.body) == ws_collapsed(cur_node.body):
        return "whitespace"
    return "changed"


def _record(diff: VersionDiff, key: str, nc: NodeChange) -> None:
    diff.per_node[key] = nc


# ----------------------------------------------------------------------------- diff_versions
def diff_versions(prev: Optional[Version], cur: Version) -> VersionDiff:
    """Match the db/inherited nodes of `cur` against `prev` (None -> everything is added)."""
    diff = VersionDiff()
    prev_nodes = diffable_nodes(prev)
    cur_nodes = diffable_nodes(cur)

    # 4. source flips (inherited <-> stored) per compiled field
    flipped = set()
    for f in COMPILED_FIELDS:
        a, b = _field_inherited(prev, f), _field_inherited(cur, f)
        if prev is not None and a is not None and b is not None and a != b:
            flipped.add(f)
    diff.source_changed = sorted(flipped, key=FIELDS.index)

    # 1. exact id, then loose last-segment key
    matched: dict = {}                       # cur_id -> prev_id
    used_prev: set = set()
    for cid in cur_nodes:
        if cid in prev_nodes:
            matched[cid] = cid
            used_prev.add(cid)
    prev_loose: dict = {}
    for pid in prev_nodes:
        if pid not in used_prev:
            prev_loose.setdefault(loose_key(pid), []).append(pid)
    for cid, cn in cur_nodes.items():
        if cid in matched:
            continue
        cands = [p for p in prev_loose.get(loose_key(cid), []) if p not in used_prev
                 and prev_nodes[p].field == cn.field]
        if cands:
            matched[cid] = cands[0]
            used_prev.add(cands[0])

    # 2. rename detection among the leftovers (same field, same depth)
    left_cur = [c for c in cur_nodes if c not in matched and cur_nodes[c].field not in flipped]
    left_prev = [p for p in prev_nodes if p not in used_prev and prev_nodes[p].field not in flipped]
    pairs = []
    for c in left_cur:
        cn = cur_nodes[c]
        for p in left_prev:
            pn = prev_nodes[p]
            if pn.field != cn.field or pn.depth != cn.depth:
                continue
            if pn.node_type == "entry" and cn.node_type == "entry" and _entry_date(p) != _entry_date(c):
                continue
            r = similarity(pn.body, cn.body)
            if r >= RENAME_RATIO:
                pairs.append((r, p, c))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    renamed: dict = {}
    taken_prev: set = set()
    for r, p, c in pairs:
        if c in renamed or p in taken_prev:
            continue
        renamed[c] = (p, r)
        taken_prev.add(p)

    # classify cur nodes
    for cid, cn in cur_nodes.items():
        nc = NodeChange(id=cid, change="added", field=cn.field, node_type=cn.node_type, title=cn.title,
                        cur_id=cid, cur_sha256=_sha(cn.body))
        if cn.field in flipped:
            nc.change = "source_changed"
            pid = matched.get(cid)
            if pid is not None:
                pn = prev_nodes[pid]
                nc.prev_id, nc.prev_sha256 = pid, _sha(pn.body)
                nc.body_changed = pn.body != cn.body
        elif cid in matched:
            pid = matched[cid]
            pn = prev_nodes[pid]
            nc.prev_id, nc.prev_sha256 = pid, _sha(pn.body)
            nc.change = _change_for_pair(pn, cn)
            nc.body_changed = pn.body != cn.body
            if nc.change == "same":
                diff.same.append(cid)
            elif nc.change == "whitespace":
                diff.whitespace_only.append(cid)
            else:
                diff.changed.append(cid)
        elif cid in renamed:
            pid, r = renamed[cid]
            pn = prev_nodes[pid]
            nc.change, nc.prev_id, nc.similarity = "renamed", pid, round(r, 3)
            nc.prev_sha256 = _sha(pn.body)
            nc.body_changed = pn.body != cn.body
            diff.renamed.append((pid, cid, round(r, 3)))
            if nc.body_changed:
                diff.changed.append(cid)
        else:
            diff.added.append(cid)
        _record(diff, cid, nc)

    # prev-only nodes
    for pid, pn in prev_nodes.items():
        if pid in used_prev or pid in taken_prev:
            continue
        if pn.field in flipped:
            if pid not in diff.per_node:
                _record(diff, pid, NodeChange(id=pid, change="source_changed", field=pn.field,
                                              node_type=pn.node_type, title=pn.title, prev_id=pid,
                                              prev_sha256=_sha(pn.body)))
            continue
        diff.removed.append(pid)
        if pid not in diff.per_node:
            _record(diff, pid, NodeChange(id=pid, change="removed", field=pn.field, node_type=pn.node_type,
                                          title=pn.title, prev_id=pid, prev_sha256=_sha(pn.body)))
    return diff


def _entry_date(node_id: str) -> Optional[str]:
    m = re.search(r"\.(\d{4}_\d{2}_\d{2})(?:_|$)", node_id)
    return m.group(1) if m else None


# ----------------------------------------------------------------------------- unified diff
def node_unified_diff(prev_node: Optional[Node], cur_node: Optional[Node], *, prev_label: str,
                      cur_label: str) -> list:
    """difflib.unified_diff over the two bodies (lineterm=''); [] when both are missing."""
    if prev_node is None and cur_node is None:
        return []
    a = (prev_node.body if prev_node is not None else "").splitlines()
    b = (cur_node.body if cur_node is not None else "").splitlines()
    return list(difflib.unified_diff(a, b, fromfile=prev_label, tofile=cur_label, lineterm=""))


def diff_stats(lines: list) -> dict:
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {"added": added, "removed": removed}


# ----------------------------------------------------------------------------- history
def _manifest_actor(version: Version) -> str:
    m = version.manifest or {}
    return m.get("actor_kind") or actor_kind(m.get("created_by") or "")


def node_history(versions: list, node_id: str) -> list:
    """[{version, id, change, body_sha256, created_at, actor_kind, renamed_from}] ascending by
    version, following rename chains backward and forward from the latest version holding the id."""
    ordered = sorted(versions, key=lambda v: v.version)
    if not ordered:
        return []
    diffs = [None] + [diff_versions(ordered[i - 1], ordered[i]) for i in range(1, len(ordered))]
    anchor = None
    for i in range(len(ordered) - 1, -1, -1):
        if node_id in ordered[i].nodes and ordered[i].nodes[node_id].owner in DIFF_OWNERS:
            anchor = i
            break
    if anchor is None:
        return []
    ids: dict = {anchor: node_id}

    def _find(nid: str, indexes) -> Optional[int]:
        """First index (in the given scan order) whose version holds nid by exact or loose key."""
        lk = loose_key(nid)
        for k in indexes:
            pool = diffable_nodes(ordered[k])
            if nid in pool:
                return k
            for cand in pool:
                if loose_key(cand) == lk and pool[cand].field == _field_of(nid, ordered):
                    return k
        return None

    # backward: follow prev_id through the pair diffs; when the node is absent in i-1, skip the
    # gap and resume from the nearest earlier version that still holds the id
    i, cur = anchor, node_id
    while i > 0:
        nc = diffs[i].per_node.get(cur)
        prev_id = nc.prev_id if nc is not None and nc.change != "removed" else None
        if prev_id is not None and prev_id in ordered[i - 1].nodes:
            i -= 1
            cur = prev_id
            ids[i] = cur
            continue
        k = _find(cur, range(i - 2, -1, -1))
        if k is None:
            break
        i = k
        cur = cur if cur in ordered[k].nodes else next(c for c in diffable_nodes(ordered[k]) if loose_key(c) == loose_key(cur))
        ids[i] = cur
    # forward: the node whose prev_id is cur in the next pair; across a gap, the nearest later
    # version holding the id
    i, cur = anchor, node_id
    while i + 1 < len(ordered):
        nxt = None
        for cid, nc in diffs[i + 1].per_node.items():
            if nc.prev_id == cur and nc.change != "removed" and cid in ordered[i + 1].nodes:
                nxt = cid
                break
        if nxt is not None:
            i += 1
            cur = nxt
            ids[i] = cur
            continue
        k = _find(cur, range(i + 2, len(ordered)))
        if k is None:
            break
        i = k
        cur = cur if cur in ordered[k].nodes else next(c for c in diffable_nodes(ordered[k]) if loose_key(c) == loose_key(cur))
        ids[i] = cur
    rows = []
    for i in sorted(ids):
        ver = ordered[i]
        nid = ids[i]
        node = ver.nodes[nid]
        if i == 0 or diffs[i] is None:
            change, renamed_from = "added", None
        else:
            nc = diffs[i].per_node.get(nid)
            change = nc.change if nc is not None else "added"
            renamed_from = nc.renamed_from if nc is not None else None
        rows.append({
            "version": ver.version, "id": nid, "change": change, "body_sha256": _sha(node.body),
            "created_at": ver.manifest.get("created_at"), "actor_kind": _manifest_actor(ver),
            "renamed_from": renamed_from,
        })
    return rows


def _field_of(node_id: str, ordered: list) -> Optional[str]:
    for v in ordered:
        n = v.nodes.get(node_id)
        if n is not None:
            return n.field
    return None


# ----------------------------------------------------------------------------- version kind
def _reminder_scope(prefix: str, node_id: str) -> bool:
    return (node_id in (f"{prefix}.directives.reminder", f"{prefix}.directives", f"{prefix}.memory",
                        f"{prefix}.memory.log")
            or node_id.startswith(f"{prefix}.memory.log."))


def version_kind(prev: Optional[Version], cur: Version, history_count: int, diff: Optional[VersionDiff] = None) -> str:
    """seed | reminder_only | rewrite | policy (timeline chip kind, spec section 9)."""
    m = cur.manifest or {}
    actor = _manifest_actor(cur)
    if cur.version == 0 or actor == "seed":
        return "seed"
    prefix = m.get("prefix") or AGENT_PREFIX.get(cur.agent_type, "") or cur.manifest.get("root_id", "").split(".")[0]
    if prev is not None:
        d = diff if diff is not None else diff_versions(prev, cur)
        touched = set(d.added) | set(d.changed) | set(d.whitespace_only) | {c for _, c, _ in d.renamed}
        removed_ok = all(_reminder_scope(prefix, i) for i in d.removed) or actor == "weekly"
        if touched and all(_reminder_scope(prefix, i) for i in touched) and removed_ok:
            return "reminder_only"
    if prev is None or int(history_count or 0) > 0:
        return "rewrite"
    return "policy"


__all__ = [
    "NodeChange", "VersionDiff", "diff_versions", "node_unified_diff", "diff_stats", "node_history",
    "version_kind", "loose_key", "norm_body", "similarity", "RENAME_RATIO", "CHANGES",
]
