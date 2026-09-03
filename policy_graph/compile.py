"""Compile side of the policy graph: read a version dir back and rebuild the prompt fields.

- compile_build      : from a GraphBuild in memory (write-time self-check)
- read_version_dir   : manifest.json + every <id>.md + edges.json + linked overlay dirs
- compile_stored     : byte-exact stored fields (None for stored_null)
- compile_effective  : inherited fields substituted (what prompt_manager._build_prompt_payload returns)
- compile_runtime_preview : the runtime assembly (decider_agent.ask_decision_agent / main.get_openai_summary /
                            feedback_agent._generate_ai_feedback) reproduced on the effective fields
- bundle             : RUSH-style bundle of node files
- rebuild_compile_order : Phase 2 helper — keep the existing order, slot in new nodes, drop removed ones

stdlib only; policy_graph.code_blocks is imported lazily (and optionally) for the runtime preview.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .decompose import NodeIntegrityError, node_from_frontmatter, node_to_frontmatter  # noqa: F401
from .frontmatter import read_node, render_frontmatter
from .model import (
    AGENT_PREFIX, Edge, FIELD_SEGMENT, FIELDS, GraphBuild, Node, TEMPLATE_FIELDS, Version,
    version_stamp,
)

CODE_BLOCKS_UNAVAILABLE = "<!-- code blocks unavailable -->"


# ----------------------------------------------------------------------------- in-memory
def compile_build(build: GraphBuild) -> dict:
    """{field: str|None} straight from the GraphBuild (db nodes in compile_order)."""
    by_id = {n.id: n for n in build.nodes}
    out = {}
    for f in FIELDS:
        meta = build.fields_meta.get(f, {})
        if meta.get("stored_null"):
            out[f] = None
            continue
        out[f] = "".join(by_id[i].text for i in build.compile_order.get(f, []))
    return out


# ----------------------------------------------------------------------------- reading
def _read_nodes_in(path: Path, nodes: dict, *, strict_names: bool = True) -> None:
    for p in sorted(Path(path).glob("*.md")):
        fm, body = read_node(p)
        node = node_from_frontmatter(fm, body)
        if strict_names and p.name != node.id + ".md":
            raise ValueError(f"{p}: filename does not match node id {node.id!r}")
        nodes[node.id] = node


def _edge_from_record(rec: dict) -> Edge:
    return Edge(
        source=rec.get("source_node_id") or rec.get("source"),
        target=rec.get("target_node_id") or rec.get("target"),
        edge_type=rec.get("edge_type") or rec.get("type"),
        confidence=rec.get("confidence", 1.0),
        provenance=rec.get("provenance", "derived"),
        version=rec.get("version", ""),
        via=rec.get("via"),
    )


def _frontmatter_edges(nodes: dict, stamp: str) -> list:
    out = []
    for node in nodes.values():
        for e in node.edges or []:
            et = e.get("type") or e.get("edge_type")
            to = e.get("to") or e.get("target")
            if not et or not to or et == "subtype_of":
                continue
            out.append(Edge(source=node.id, target=str(to), edge_type=str(et),
                            confidence=e.get("confidence", 1.0), provenance=e.get("provenance", "authored"),
                            version=stamp, via=e.get("via")))
    return out


def read_version_dir(path: Path) -> Version:
    """Read a materialized version dir (plus the overlay dirs the manifest links to)."""
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json missing in {path}")
    with open(manifest_path, "rb") as fh:
        manifest = json.loads(fh.read().decode("utf-8"))
    nodes: dict = {}
    _read_nodes_in(path, nodes)
    for key in ("code", "ltm"):
        link = (manifest.get(key) or {}).get("dir")
        if link:
            overlay = (path / link).resolve() if not Path(link).is_absolute() else Path(link)
            if overlay.is_dir():
                _read_nodes_in(overlay, nodes, strict_names=False)
    edges: list = []
    seen = set()
    edges_path = path / "edges.json"
    if edges_path.exists():
        with open(edges_path, "rb") as fh:
            records = json.loads(fh.read().decode("utf-8") or "[]")
        for rec in records:
            e = _edge_from_record(rec)
            if e.key() not in seen:
                seen.add(e.key())
                edges.append(e)
    stamp = version_stamp(manifest.get("agent_type", ""), manifest.get("config_hash", ""), manifest.get("version", 0))
    for e in _frontmatter_edges(nodes, stamp):
        if e.key() not in seen:
            seen.add(e.key())
            edges.append(e)
    return Version(path=path, manifest=manifest, nodes=nodes, edges=edges)


# ----------------------------------------------------------------------------- compiling
def _field_meta(version: Version, field: str) -> dict:
    return (version.manifest.get("fields") or {}).get(field) or {}


def _join(version: Version, ids: list) -> str:
    parts = []
    for i in ids:
        node = version.nodes.get(i)
        if node is None:
            raise KeyError(f"compile_order references missing node {i!r}")
        parts.append(node.text)
    return "".join(parts)


def compile_stored(version: Version) -> dict:
    """Byte-exact stored fields; None when manifest.fields[F].stored_null."""
    order = version.manifest.get("compile_order") or {}
    out = {}
    for f in FIELDS:
        if _field_meta(version, f).get("stored_null"):
            out[f] = None
            continue
        out[f] = _join(version, order.get(f, []))
    return out


def _inherited_ids(version: Version, field: str) -> list:
    meta = _field_meta(version, field)
    ids = meta.get("inherited_order")
    if ids:
        return list(ids)
    cands = [n for n in version.nodes.values() if n.field == field and n.owner == "default-file"]
    cands.sort(key=lambda n: (n.order, n.id))
    return [n.id for n in cands]


def compile_effective(version: Version) -> dict:
    """Stored fields with inherited defaults substituted (None → "")."""
    stored = compile_stored(version)
    out = {}
    for f in FIELDS:
        if _field_meta(version, f).get("inherited"):
            out[f] = _join(version, _inherited_ids(version, f))
        else:
            out[f] = stored[f] if stored[f] is not None else ""
    return out


# ----------------------------------------------------------------------------- runtime preview
def _code_blocks_for(version: Version) -> Optional[list]:
    """Code-owned blocks as dicts {id,title,text,position,source_file,source_symbol,condition}.

    Prefers the version's own code nodes (overlay dir); falls back to policy_graph.code_blocks;
    None when neither is available."""
    prefix = version.manifest.get("prefix") or AGENT_PREFIX.get(version.agent_type, "")
    nodes = [n for n in version.nodes.values() if n.owner == "code"]
    if nodes:
        nodes.sort(key=lambda n: (n.order, n.id))
        return [{
            "id": n.id, "title": n.title, "text": n.body, "position": n.extra.get("position"),
            "source_file": n.extra.get("source_file"), "source_symbol": n.extra.get("source_symbol"),
            "condition": n.extra.get("condition"),
        } for n in nodes]
    try:
        from . import code_blocks as cb  # optional module (another track)
    except Exception:
        return None
    blocks = []
    for b in getattr(cb, "CODE_BLOCKS", []):
        bid = getattr(b, "id", None) or b[0]
        if not str(bid).startswith(prefix + "."):
            continue
        blocks.append({
            "id": bid, "title": getattr(b, "title", None), "text": getattr(b, "text", ""),
            "position": getattr(b, "position", None), "source_file": getattr(b, "source_file", None),
            "source_symbol": getattr(b, "source_symbol", None), "condition": getattr(b, "condition", None),
        })
    return blocks


def _block(blocks: Optional[list], block_id: str) -> Optional[dict]:
    if not blocks:
        return None
    for b in blocks:
        if b["id"] == block_id:
            return b
    return None


def _block_text(b: Optional[dict], block_id: str) -> str:
    return b["text"] if b is not None else f"<!-- code blocks unavailable: {block_id} -->"


def _marker(b: dict) -> str:
    src = f" ({b['source_file']}:{b['source_symbol']})" if b.get("source_file") else ""
    return f"<!-- per-cycle: {b.get('title') or b['id']}{src} -->"


def _code_sha(version: Version) -> str:
    sha = (version.manifest.get("code") or {}).get("sha")
    if sha:
        return str(sha)
    try:
        from . import code_blocks as cb
        return str(getattr(cb, "CODE_SHA", "unknown"))
    except Exception:
        return "unknown"


def compile_runtime_preview(version: Version, *, is_margin_account: bool) -> dict:
    """{"system": str, "user": str, "label": str, "fires": {...}} — spec §4.2."""
    eff = compile_effective(version)
    agent = version.agent_type
    prefix = version.manifest.get("prefix") or AGENT_PREFIX.get(agent, "")
    blocks = _code_blocks_for(version)
    system = eff["system_prompt"]
    user = eff["user_prompt_template"]
    soul, strategy, memory = eff["soul"], eff["strategy_directives"], eff["memory"]
    fires: dict = {}

    if agent in ("DeciderAgent", "SummarizerAgent", "CompanyExtractionAgent"):
        if soul:
            system = f"{system}\n\n## AGENT IDENTITY\n{soul}"
        if strategy and "{strategy_directives}" in system:
            system = system.replace("{strategy_directives}", strategy)
        elif strategy:
            system = system + "\n\n" + strategy
        if memory:
            system = f"{system}\n\n## LESSONS FROM EXPERIENCE\n{memory}"

    if agent == "DeciderAgent":
        jf_id = f"{prefix}.code.json_fallback"
        fires[jf_id] = "JSON" not in user.upper()
        if fires[jf_id]:
            user += _block_text(_block(blocks, jf_id), jf_id)
        cf_id = f"{prefix}.code.crowd_fade"
        fires[cf_id] = "CROWD-FADE" not in user and "CROWD-FADE" not in (strategy or "")
        if fires[cf_id]:
            user = user.rstrip() + "\n\n" + _block_text(_block(blocks, cf_id), cf_id).strip()
        cp_id = f"{prefix}.code.cash_playbook"
        fires[cp_id] = (not is_margin_account) and "⏳ CASH ACCOUNT PLAYBOOK" not in user
        if fires[cp_id]:
            user = user.rstrip() + "\n\n" + _block_text(_block(blocks, cp_id), cp_id).strip()
        if blocks is None:
            user = user + "\n\n" + CODE_BLOCKS_UNAVAILABLE
        else:
            dynamic = [b for b in blocks if b.get("position") == "user_prompt_dynamic"]
            tails = [b for b in blocks if b.get("position") == "user_prompt_tail"]
            if dynamic:
                user = user + "\n\n" + "\n".join(_marker(b) for b in dynamic)
            for b in tails:
                user = user + b["text"]
    elif agent == "SummarizerAgent":
        fs_id = f"{prefix}.code.feedback_suffix"
        b = _block(blocks, fs_id)
        if b is not None:
            suffix = b["text"].replace("{summarizer_feedback}", "<!-- per-cycle: summarizer feedback -->")
        elif blocks is None:
            suffix = CODE_BLOCKS_UNAVAILABLE
        else:
            suffix = "\nPERFORMANCE FEEDBACK: <!-- per-cycle: summarizer feedback -->"
        system = system + "\n\n" + suffix
    elif agent == "FeedbackAgent":
        sb_id = f"{prefix}.code.system_base"
        base = _block(blocks, sb_id)
        system = (base["text"] if base is not None else
                  (CODE_BLOCKS_UNAVAILABLE if blocks is None else f"<!-- code blocks unavailable: {sb_id} -->"))
        if soul:
            system = f"{system}\n\n## AGENT IDENTITY\n{soul}"
        bi = _block(blocks, f"{prefix}.code.base_instructions")
        jf = _block(blocks, f"{prefix}.code.json_format")
        if blocks is None:
            user = CODE_BLOCKS_UNAVAILABLE
        else:
            parts = [b["text"] for b in (bi, jf) if b is not None]
            user = "\n".join(parts) if parts else CODE_BLOCKS_UNAVAILABLE

    return {
        "system": system,
        "user": user,
        "label": f"assembled from code as of {_code_sha(version)}; per-cycle data omitted",
        "fires": fires,
    }


# ----------------------------------------------------------------------------- bundle
def node_file_text(node: Node, stamp: str) -> str:
    return "---\n" + render_frontmatter(node_to_frontmatter(node, stamp)) + "\n---\n" + node.body


def bundle(version: Version, *, include_code: bool = True, include_ltm: bool = True) -> str:
    """RUSH load_policy_markdown port: root first, then lexicographic; '<!-- id.md -->' markers."""
    m = version.manifest
    prefix = m.get("prefix") or AGENT_PREFIX.get(version.agent_type, "")
    stamp = version_stamp(m.get("agent_type", ""), m.get("config_hash", ""), m.get("version", 0))
    root_id = m.get("root_id") or f"{prefix}.root"
    ids = sorted(version.nodes)
    ordered = ([root_id] if root_id in version.nodes else []) + [i for i in ids if i != root_id]
    parts = []
    for i in ordered:
        if not include_code and (i == f"{prefix}.code" or i.startswith(f"{prefix}.code.")):
            continue
        if not include_ltm and (i == f"{prefix}.ltm" or i.startswith(f"{prefix}.ltm.")):
            continue
        parts.append(f"\n\n<!-- {i}.md -->\n" + node_file_text(version.nodes[i], stamp).strip() + "\n")
    return "".join(parts).strip() + "\n"


# ----------------------------------------------------------------------------- Phase 2 helper
def rebuild_compile_order(version: Version, changed: set) -> dict:
    """Compile order after node edits: existing order kept, new nodes after their last sibling
    (or right after their parent), moved subtrees move together, removed ids dropped."""
    old = version.manifest.get("compile_order") or {}
    nodes = version.nodes
    prefix = version.manifest.get("prefix") or AGENT_PREFIX.get(version.agent_type, "")
    out = {}
    for f in FIELDS:
        db_nodes = [n for n in nodes.values() if n.field == f and n.owner == "db"]
        if f in TEMPLATE_FIELDS:
            out[f] = [n.id for n in sorted(db_nodes, key=lambda n: n.id)][:1]
            continue
        prev = [i for i in old.get(f, []) if i in nodes and nodes[i].field == f and nodes[i].owner == "db"]
        rank = {i: k for k, i in enumerate(prev)}
        group_id = f"{prefix}.{FIELD_SEGMENT[f]}"
        present = {n.id: n for n in db_nodes}
        children: dict = {}
        for n in db_nodes:
            children.setdefault(n.parent, []).append(n.id)
        for kids in children.values():
            kids.sort(key=lambda i: (0, rank[i], "") if i in rank else (1, present[i].order, i))
        order: list = []

        def walk(i):
            order.append(i)
            for c in children.get(i, []):
                if c not in order:
                    walk(c)

        if group_id in present:
            walk(group_id)
        for n in sorted(db_nodes, key=lambda n: (rank.get(n.id, 10 ** 9), n.order, n.id)):
            if n.id not in order:
                walk(n.id)
        old_set = set(prev)
        for i in order:
            node = present[i]
            if i in (changed or set()) and i not in old_set and node.sep_before == "" and node.sep_after == "":
                node.sep_after = "\n\n"
        for a, b in zip(order, order[1:]):
            if present[a].sep_after == "" and present[b].sep_before == "":
                present[a].sep_after = "\n\n"   # a node that stopped being last needs a separator
        if order:
            present[order[-1]].sep_after = ""
        out[f] = order
    return out


__all__ = [
    "compile_build", "read_version_dir", "compile_stored", "compile_effective", "compile_runtime_preview",
    "bundle", "rebuild_compile_order", "node_file_text", "NodeIntegrityError", "CODE_BLOCKS_UNAVAILABLE",
]
