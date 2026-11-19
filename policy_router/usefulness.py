"""Blinded local review of saved, scored optional guidelines. Never calls a model."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.exc import IntegrityError

from policy_graph import service
from policy_graph.frontmatter import read_node
from policy_graph.decompose import node_from_frontmatter
from policy_graph.lessons import format_memory_line, ltm_title
from policy_graph.model import ID_RE

from .decisions_log import _safe_context_summary
from .nodes import from_graph_node

TABLE = "policy_router_usefulness_reviews"
DDL = """CREATE TABLE IF NOT EXISTS policy_router_usefulness_reviews (
 config_hash VARCHAR(50) NOT NULL, comparison_id INTEGER NOT NULL, node_id TEXT NOT NULL,
 revision INTEGER NOT NULL, judgment TEXT NOT NULL CHECK(judgment IN ('needed','irrelevant','clear')),
 evidence_hash TEXT NOT NULL, reviewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(config_hash,comparison_id,node_id,revision))"""
LIMIT = 100


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _fetch_ids(conn, query, config, ids):
    if not ids:
        return []
    stmt = text(query).bindparams(bindparam("ids", expanding=True))
    return conn.execute(stmt, {"h": config, "ids": sorted(set(ids))}).mappings().all()


def _legacy_at_or_before(updated_at, at):
    try:
        return datetime.fromisoformat(str(updated_at)) <= datetime.fromisoformat(str(at))
    except (TypeError, ValueError):
        return False


def _original_text(config, comparison, node, memories, repo_root, archive):
    ident = node["node_id"]
    if node["kind"] == "ltm":
        m = re.fullmatch(r"DA\.ltm\.(\d+)", ident)
        row = memories.get(int(m.group(1))) if m else None
        if not row:
            return None
        body = format_memory_line(row).strip()
        legacy_ok = (node.get("title") == ltm_title(row) and node.get("chars") == len(format_memory_line(row)) + 1
                     and _legacy_at_or_before(row["updated_at"], comparison["decided_at"]))
    else:
        version = comparison["prompt_version"]
        if not ID_RE.fullmatch(ident) or not re.fullmatch(r"[a-zA-Z0-9_-]+", config) or not isinstance(version, int):
            return None
        key = (version, ident)
        if key not in archive:
            path = Path(repo_root)/"agents"/"decider"/"policy-graph"/config/f"v{version}"/f"{ident}.md"
            try:
                archive[key] = from_graph_node(node_from_frontmatter(*read_node(path)))
            except (OSError, ValueError):
                archive[key] = None
        original = archive[key]
        if original is None or original.node_id != ident or original.kind != "entry":
            return None
        body = original.text
        legacy_ok = node.get("title") == original.meta["title"] and node.get("chars") == original.chars
    fingerprint = node.get("text_sha256")
    if fingerprint:
        return (body, "Verified text hash") if _sha(body) == fingerprint else None
    return (body, "Matched historical record by ID, title and length") if legacy_ok else None


def _pool(conn, config, repo_root):
    tables = inspect(conn)
    if not tables.has_table("policy_router_comparisons"):
        return [], 0
    cycles = conn.execute(text("""SELECT id,run_id,prompt_version,source_input_id,decided_at,request_hash,policy_hash,
            comparison_json,nodes_json FROM policy_router_comparisons WHERE config_hash=:h
            AND provider='openai_decisions' AND source_kind='live' AND status='ok' ORDER BY id DESC LIMIT :lim"""),
                          {"h": config, "lim": LIMIT}).mappings().all()
    ids = [c["id"] for c in cycles]
    labels = {}
    if tables.has_table(TABLE):
        for row in _fetch_ids(conn, """SELECT comparison_id,node_id,revision,judgment,evidence_hash FROM policy_router_usefulness_reviews
              WHERE config_hash=:h AND comparison_id IN :ids ORDER BY revision DESC""", config, ids):
            labels.setdefault((row["comparison_id"], row["node_id"]), row)
    input_ids = [c["source_input_id"] for c in cycles if c["source_input_id"]]
    inputs = {r["id"]: r for r in _fetch_ids(conn, """SELECT id,run_id,decided_at,context_json FROM decider_inputs
        WHERE config_hash=:h AND call_kind='decide' AND id IN :ids""", config, input_ids)} if tables.has_table("decider_inputs") else {}
    parsed = [(c, json.loads(c["nodes_json"]), json.loads(c["comparison_json"])) for c in cycles]
    memory_ids = {int(m.group(1)) for _, nodes, _ in parsed for node in nodes
                  if (m := re.fullmatch(r"DA\.ltm\.(\d+)", node.get("node_id", "")))}
    memories = {r["id"]: r for r in _fetch_ids(conn, """SELECT id,kind,ticker,content,updated_at FROM decider_memory
            WHERE config_hash=:h AND id IN :ids""", config, memory_ids)} if tables.has_table("decider_memory") else {}
    items, archive, source_cache = [], {}, {}
    for cycle, nodes, comparison in parsed:
        saved = inputs.get(cycle["source_input_id"])
        context = {}
        manifest = comparison.get("image_manifest") or {}
        if saved and saved["run_id"] == cycle["run_id"]:
            raw = json.loads(saved["context_json"] or "{}")
            if isinstance(raw, dict) and any(name in raw for name in ("regime", "holdings", "watchlist", "news", "entities")):
                context = _safe_context_summary(raw)
                manifest = manifest or raw.get("image_manifest") or {}
        for node in nodes:
            if node.get("kind") not in ("ltm", "entry") or node.get("decisions_choice") not in ("include", "exclude"):
                continue
            ident = node["node_id"]
            key = (cycle["id"], ident)
            original = _original_text(config, cycle, node, memories, repo_root, archive)
            label = labels.get(key)
            revision = label["revision"] if label else 0
            judgment = label["judgment"] if label and label["judgment"] != "clear" else None
            evidence_hash = None
            if original and context:
                evidence_hash = _sha(json.dumps([config, cycle["prompt_version"], cycle["policy_hash"], cycle["request_hash"],
                                                 cycle["id"], ident, original[0], context], sort_keys=True))
            item = {"comparison_id": cycle["id"], "node_id": ident, "judgment": judgment,
                          "revision": revision, "run_id": cycle["run_id"], "as_of": str(cycle["decided_at"]),
                          "source_input_id": cycle["source_input_id"], "input_at": str(saved["decided_at"]) if saved else None,
                          "version": cycle["prompt_version"], "context": context,
                          "evidence_hash": evidence_hash, "body": original[0] if original else None,
                          "basis": original[1] if original else None, "choice": node["decisions_choice"],
                          "active": comparison.get("requested_mode") == "active", "served": node.get("served_in_prompt"),
                          "manifest": manifest, "order": _sha(f"{config}/{key[0]}/{ident}")}
            if judgment:
                if original and context:
                    _add_headlines(conn, config, item, source_cache)
                if item["evidence_hash"] != label["evidence_hash"]:
                    item["judgment"] = None
            items.append(item)
    return sorted(items, key=lambda row: row["order"]), len(cycles)


def _add_headlines(conn, config, item, cache=None):
    """Show only source headlines saved by the cycle cutoff, never the reply, outcome or account state."""
    from .features import MAX_SUMMARIES, parse_summary_row
    if "headlines" in item:
        return
    key = item["comparison_id"]
    if cache is not None and key in cache:
        basis, heads = cache[key]
    else:
        basis, heads = "Legacy same-run headlines through the saved input time", []
        manifest = item["manifest"]
        refs = {}
        if manifest:
            basis = "Headlines from source summaries in the frozen image manifest"
            if manifest.get("config_hash") == config and manifest.get("decision_run_id") == item["run_id"]:
                for ref in [*(manifest.get("images") or []), *(manifest.get("omissions") or [])]:
                    raw_id = str(ref.get("summary_id") or "")
                    if raw_id.isdecimal() and len(raw_id) <= 10 and ref.get("reason") != "summary_scope_mismatch":
                        refs[int(raw_id)] = (ref.get("source_run_id"), ref.get("source_agent"))
        records = []
        if inspect(conn).has_table("summaries"):
            if refs:
                stmt = text("""SELECT id,run_id,agent,data FROM summaries
                    WHERE config_hash=:h AND id IN :ids AND timestamp<=:at ORDER BY timestamp,id""").bindparams(
                    bindparam("ids", expanding=True))
                rows = conn.execute(stmt, {"h": config, "ids": sorted(refs), "at":item["input_at"]})
                records = [r.data for r in rows if refs[r.id] == (r.run_id, r.agent)]
            elif not manifest:
                records = conn.execute(text("""SELECT data FROM summaries WHERE config_hash=:h AND run_id=:r
                    AND timestamp<=:at ORDER BY timestamp DESC,id DESC LIMIT :lim"""), {
                    "h": config, "r": item["run_id"], "at": item["input_at"], "lim": MAX_SUMMARIES}).scalars()
        for data in records:
            summary = parse_summary_row(data)
            if summary:
                heads.extend(h[:400] for h in summary["headlines"][:3])
        heads = list(dict.fromkeys(heads))
        if cache is not None:
            cache[key] = (basis, heads)
    item["headline_basis"], item["headlines"] = basis, heads
    item["evidence_hash"] = _sha(json.dumps([item["evidence_hash"], basis, heads]))


def _metrics(items, cycles):
    reviewed = [x for x in items if x["judgment"]]
    needed = [x for x in reviewed if x["judgment"] == "needed"]
    missed = [x for x in needed if x["choice"] == "exclude"]
    actual = [x for x in needed if x["active"] and isinstance(x["served"], bool)]
    return {"cycles": cycles, "scored": len(items), "reviewed": len(reviewed), "unjudged": len(items)-len(reviewed),
            "unavailable": sum(not x["evidence_hash"] for x in items), "needed": len(needed), "proposed_misses": len(missed),
            "reviewed_recall": (len(needed)-len(missed))/len(needed) if needed else None,
            "active_needed": len(actual), "active_omitted": sum(not x["served"] for x in actual)}


def review_view(engine, config, repo_root, *, queue="unreviewed", offset=0):
    if queue not in ("unreviewed", "reviewed") or not isinstance(offset, int) or not 0 <= offset <= 40000:
        raise ValueError("Invalid review queue or offset")
    with engine.connect() as conn:
        items, cycles = _pool(conn, config, repo_root)
        candidates = [x for x in items if x["evidence_hash"] and bool(x["judgment"]) == (queue == "reviewed")]
        item = candidates[offset % len(candidates)].copy() if candidates else None
        if item:
            _add_headlines(conn, config, item)
    if item:
        for key in ("order", "choice", "served", "active", "manifest"):
            item.pop(key)
    return {"config_hash": config, "window_cycles": LIMIT, "summary": _metrics(items, cycles),
            "queue_size": len(candidates), "item": item}


def save_review(engine, config, repo_root, payload):
    judgment = payload.get("judgment")
    comparison = payload.get("comparison_id")
    ident = payload.get("node_id")
    expected = payload.get("revision")
    if (judgment not in ("needed", "irrelevant", "clear") or type(comparison) is not int
            or type(expected) is not int or expected < 0 or not isinstance(ident, str)
            or not ID_RE.fullmatch(ident) or payload.get("config_hash") != config):
        raise ValueError("Invalid config, candidate or judgment")
    with engine.begin() as conn:
        items, _ = _pool(conn, config, repo_root)
        item = next((x for x in items if x["comparison_id"] == comparison and x["node_id"] == ident), None)
        if not item or not item["evidence_hash"]:
            raise service.NotFound("Scored candidate with matching cycle evidence unavailable")
        _add_headlines(conn, config, item)
        if item["evidence_hash"] != payload.get("evidence_hash") or item["revision"] != expected:
            return False
        if judgment == (item["judgment"] or "clear"):
            return True
        conn.execute(text(DDL))
        try:
            with conn.begin_nested():
                conn.execute(text("""INSERT INTO policy_router_usefulness_reviews
                    (config_hash,comparison_id,node_id,revision,judgment,evidence_hash)
                    VALUES(:h,:c,:n,:r,:j,:e)"""), {"h": config, "c": comparison, "n": ident, "r": expected+1,
                                                    "j": judgment, "e": item["evidence_hash"]})
        except IntegrityError:
            return False
    return True
