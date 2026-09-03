"""Edge derivation, graph validation and edges.json I/O.

derive_edges() is pure over a Node list: hierarchy (`subtype_of` from parent), runtime
assembly (`includes`), wiki-links and shared tags (`related_to`), ticker mentions (`cites`,
creating virtual '<P>.ticker.SYM' nodes in the passed list), token-Jaccard overlap between
guideline nodes and code/ltm nodes (`overlaps`), the hand map in code_blocks.CONSTRAINS
(`constrains`) and any authored frontmatter edges. edges.json is the sorted union.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from .code_blocks import CONSTRAINS
from .model import EDGE_TYPES, ID_RE, LINK_ALIASES, STOPWORDS, Edge, Node, PREFIX_AGENT

WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:\|[^\]]*)?\]\]")
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
TOKEN_RE = re.compile(r"[a-z0-9]+")
OVERLAP_THRESHOLD = 0.35
TAG_MAX_NODES = 6
GUIDELINE_TYPES = {"rule", "lesson", "section", "identity"}
GUIDELINE_OWNERS = {"db", "default-file"}
OVERLAY_OWNERS = {"code", "decider_memory"}
SUBTYPE = "subtype_of"
_FIELD_RANK = {"strategy_directives": 0, "soul": 1, "memory": 2}


# ----------------------------------------------------------------------------- helpers
def _prefix(node_id: str) -> str:
    return node_id.split(".", 1)[0]


def _last(node_id: str) -> str:
    return node_id.rsplit(".", 1)[-1]


def _loose(s: str) -> str:
    return re.sub(r"[_\-\s]", "", (s or "").lower())


def tokens(text: str) -> set:
    return {t for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 3 and t not in STOPWORDS}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _first_text_node(nodes: Iterable[Node], field: str) -> bool:
    return any(n.field == field and n.owner in GUIDELINE_OWNERS and (n.body or "").strip() for n in nodes)


def resolve_link(target: str, by_id: dict, *, prefix: str) -> Optional[str]:
    """[[target]] → node id: exact id, then last-segment equality ignoring _/-/case, then a node
    carrying the tag, then model.LINK_ALIASES. None when unresolved."""
    t = (target or "").strip()
    if not t:
        return None
    if t in by_id:
        return t
    loose = _loose(t.lstrip("#"))
    same_prefix = [i for i in by_id if _prefix(i) == prefix]

    def pref(i):   # ties: rules in directives before soul before memory, then shortest id
        return (_FIELD_RANK.get(by_id[i].field, 9), len(i), i)

    for pool in (same_prefix, list(by_id)):
        hits = [i for i in pool if _loose(_last(i)) == loose]
        if hits:
            return sorted(hits, key=pref)[0]
    for pool in (same_prefix, list(by_id)):
        hits = [i for i in pool if any(_loose(tag) == loose for tag in by_id[i].tags or [])]
        if hits:
            return sorted(hits, key=pref)[0]
    alias = LINK_ALIASES.get(t) or LINK_ALIASES.get(t.lower())
    if alias and alias in by_id:
        return alias
    return None


def ticker_node_id(prefix: str, sym: str) -> str:
    """'<P>.ticker.<sym>' — the segment is lowercased to satisfy model.ID_RE (filename == id + '.md');
    the symbol itself lives in title/tickers."""
    return f"{prefix}.ticker.{sym.lower()}"


def _ticker_node(prefix: str, sym: str) -> Node:
    return Node(
        id=ticker_node_id(prefix, sym), agent=PREFIX_AGENT.get(prefix, ""), title=sym, node_type="ticker",
        parent=f"{prefix}.root", field=None, body="", polarity="structure", polarity_source="override",
        owner="generated", status="generated", compiled="never", locked=False, provenance="derived:ticker",
        tickers=[sym],
    )


# ----------------------------------------------------------------------------- derive
def derive_edges(nodes: list, *, version_stamp: str) -> list:
    """All Phase-1 edges for one version. Virtual ticker nodes are appended to `nodes` in place."""
    by_id = {n.id: n for n in nodes}
    edges: list = []
    seen: set = set()

    def add(source, target, edge_type, *, confidence=1.0, provenance="derived", via=None):
        key = (source, target, edge_type)
        if source == target or key in seen:
            return
        seen.add(key)
        edges.append(Edge(source=source, target=target, edge_type=edge_type, confidence=confidence,
                          provenance=provenance, version=version_stamp, via=via))

    def ensure_ticker(prefix: str, sym: str) -> str:
        tid = ticker_node_id(prefix, sym)
        if tid not in by_id and f"{prefix}.root" in by_id:
            node = _ticker_node(prefix, sym)
            nodes.append(node)
            by_id[tid] = node
        return tid

    # 1. hierarchy
    for n in nodes:
        if n.parent:
            add(n.id, n.parent, SUBTYPE, provenance="derived:hierarchy")

    # 2. runtime assembly
    prefixes = sorted({_prefix(n.id) for n in nodes})
    for p in prefixes:
        sys_id, user_id = f"{p}.template.system", f"{p}.template.user"
        sys_node = by_id.get(sys_id)
        if sys_node is not None:
            sys_body = sys_node.body or ""
            if f"{p}.directives" in by_id and _first_text_node(nodes, "strategy_directives"):
                via = "{strategy_directives}" if "{strategy_directives}" in sys_body else "appended"
                add(sys_id, f"{p}.directives", "includes", provenance="derived:assembly", via=via)
            if f"{p}.soul" in by_id and _first_text_node(nodes, "soul"):
                add(sys_id, f"{p}.soul", "includes", provenance="derived:assembly", via="## AGENT IDENTITY")
            if f"{p}.memory" in by_id and _first_text_node(nodes, "memory"):
                add(sys_id, f"{p}.memory", "includes", provenance="derived:assembly", via="## LESSONS FROM EXPERIENCE")
        if user_id in by_id:
            code = sorted((n for n in nodes if n.owner == "code" and _prefix(n.id) == p and n.node_type == "code"),
                          key=lambda n: (n.order, n.id))
            for c in code:
                add(user_id, c.id, "includes", provenance="derived:assembly", via=c.extra.get("position"))
            if p == "DA" and "DA.ltm" in by_id:
                add(user_id, "DA.ltm", "includes", provenance="derived:assembly", via="user_prompt_dynamic")
            if f"{p}.runtime.inputs" in by_id:
                add(user_id, f"{p}.runtime.inputs", "includes", provenance="derived:assembly", via="per-cycle")

    # 3. wiki-links → related_to / cites
    for n in list(nodes):
        p = _prefix(n.id)
        raw = list(n.links or [])
        raw += [m.strip() for m in WIKILINK_RE.findall(n.body or "")]
        for target in dict.fromkeys(t for t in raw if t):
            target = target.strip()
            if target in by_id:
                add(n.id, target, "related_to", provenance="derived:wikilink", via=f"[[{target}]]")
                continue
            if TICKER_RE.match(target):          # [[IRDM]] is a ticker cite, never a tag/section match
                add(n.id, ensure_ticker(p, target), "cites", provenance="derived:ticker", via=f"[[{target}]]")
                continue
            resolved = resolve_link(target, by_id, prefix=p)
            if resolved is not None:
                add(n.id, resolved, "related_to", provenance="derived:wikilink", via=f"[[{target}]]")

    # 4. tickers → cites
    for n in list(nodes):
        if n.node_type == "ticker":
            continue
        p = _prefix(n.id)
        syms = [str(t).upper() for t in (n.tickers or []) if TICKER_RE.match(str(t).upper())]
        syms += [t for t in (n.tags or []) if isinstance(t, str) and TICKER_RE.match(t)]
        for sym in dict.fromkeys(syms):
            add(n.id, ensure_ticker(p, sym), "cites", provenance="derived:ticker", via=f"#{sym}")

    # 5. shared tags → related_to (only tags present in <= TAG_MAX_NODES nodes)
    tag_map: dict = {}
    for n in nodes:
        if n.node_type == "ticker":
            continue
        for tag in dict.fromkeys(str(t).lstrip("#") for t in (n.tags or []) if t):
            if TICKER_RE.match(tag):
                continue
            tag_map.setdefault(tag, []).append(n.id)
    for tag, ids in tag_map.items():
        if len(ids) < 2 or len(ids) > TAG_MAX_NODES:
            continue
        ids = sorted(ids)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                add(a, b, "related_to", provenance="derived:tag", via=f"#{tag}")

    # 6. overlaps (guideline <-> code/ltm), token Jaccard
    guidelines = [n for n in nodes if n.owner in GUIDELINE_OWNERS and n.node_type in GUIDELINE_TYPES]
    overlays = [n for n in nodes if n.owner in OVERLAY_OWNERS and (n.body or "").strip()]
    otoks = [(o, tokens(o.body)) for o in overlays]
    for g in guidelines:
        gt = tokens(g.body)
        if not gt:
            continue
        for o, ot in otoks:
            j = jaccard(gt, ot)
            if j >= OVERLAP_THRESHOLD:
                add(g.id, o.id, "overlaps", confidence=round(j, 3), provenance="derived:similarity")

    # 7. constrains from the hand map (only when the rule exists in this version)
    for code_id, rule_slugs in CONSTRAINS.items():
        if code_id not in by_id:
            continue
        p = _prefix(code_id)
        for slug in rule_slugs:
            hits = [n for n in nodes if _prefix(n.id) == p and n.owner in GUIDELINE_OWNERS
                    and _loose(_last(n.id)) == _loose(slug)]
            hits.sort(key=lambda n: (n.node_type != "rule", n.id))
            if hits:
                add(code_id, hits[0].id, "constrains", provenance="authored:code_map")

    # 8. authored frontmatter edges (subtype_of skipped: hierarchy truth is parent:)
    for n in nodes:
        for e in n.edges or []:
            et, to = e.get("type"), e.get("to")
            if not et or not to or et == SUBTYPE:
                continue
            add(n.id, to, et, confidence=e.get("confidence", 1.0), provenance="authored", via=e.get("via"))

    edges.sort(key=lambda e: (e.source, e.edge_type, e.target))
    return edges


# ----------------------------------------------------------------------------- validate
def validate_graph(nodes: list, edges: list, *, root_id: str) -> list:
    """Structural problems (empty list = ok): one root, valid ids, parents exist and chain to the
    root without cycles, no duplicate ids/edges, edge endpoints exist, known edge types."""
    problems: list = []
    by_id: dict = {}
    for n in nodes:
        if n.id in by_id:
            problems.append(f"duplicate node id {n.id}")
        by_id[n.id] = n
        if not ID_RE.match(n.id):
            problems.append(f"bad node id {n.id!r}")
    roots = [n.id for n in nodes if not n.parent]
    if roots != [root_id]:
        problems.append(f"expected exactly one root {root_id!r}, found {roots}")
    for n in nodes:
        if n.parent and n.parent not in by_id:
            problems.append(f"{n.id}: parent {n.parent} does not exist")
    for n in nodes:
        seen, cur = set(), n
        while cur.parent:
            if cur.id in seen:
                problems.append(f"{n.id}: parent cycle through {cur.id}")
                break
            seen.add(cur.id)
            nxt = by_id.get(cur.parent)
            if nxt is None:
                break
            cur = nxt
        else:
            if cur.id != root_id and n.parent:
                problems.append(f"{n.id}: parent chain ends at {cur.id}, not {root_id}")
    keys: set = set()
    for e in edges:
        k = e.key()
        if k in keys:
            problems.append(f"duplicate edge {k}")
        keys.add(k)
        if e.source not in by_id:
            problems.append(f"edge {k}: source missing")
        if e.target not in by_id:
            problems.append(f"edge {k}: target missing")
        if e.edge_type not in EDGE_TYPES:
            problems.append(f"edge {k}: unknown edge_type")
        if e.source == e.target:
            problems.append(f"edge {k}: self-loop")
    return problems


# ----------------------------------------------------------------------------- edges.json
def write_edges_json(path: Path, edges: list) -> None:
    records = [e.to_record() for e in sorted(edges, key=lambda e: (e.source, e.edge_type, e.target))]
    data = json.dumps(records, indent=1, ensure_ascii=False) + "\n"
    with open(Path(path), "wb") as fh:
        fh.write(data.encode("utf-8"))


def read_edges_json(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        records = json.loads(fh.read().decode("utf-8") or "[]")
    return [
        Edge(source=r["source_node_id"], target=r["target_node_id"], edge_type=r["edge_type"],
             confidence=r.get("confidence", 1.0), provenance=r.get("provenance", "derived"),
             version=r.get("version", ""), via=r.get("via"))
        for r in records
    ]
