"""A versioned policy landscape, with separate prospective and replay evidence.

The coordinates describe text, never expected profit. A saved PCA basis and saved
point coordinates keep an unchanged revision fixed when later rules arrive. The
optional semantic service is loopback-only; if unavailable on first construction,
a clearly named local lexical projection is frozen instead. No model calls or
trading operations happen here.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import time

import numpy as np
from sqlalchemy import inspect, text

from . import service
from .decompose import decompose_row
from .model import AGENT_DIR, COMPILED_FIELDS, RowMeta
from policy_router.embed import EmbedCache, EmbeddingClient, DEFAULT_EMBED_MODEL

FORMAT = 1
LEXICAL_DIM = 512
MAX_LANDMARKS = 5000


def _sha(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _structural(node, children):
    if node.node_type in ("root", "field"):
        return True
    if node.node_type != "section":
        return False
    body = re.sub(r"^\s*#{1,6}[^\n]*(?:\n|$)", "", node.body, flags=re.M).strip()
    return not body or (node.id in children and re.fullmatch(r"\*[^*]+\*", body) is not None)


def history(ctx, agent):
    """Only immutable prompt-version policy text; mutable LTM is not reconstructed."""
    revisions, versions, previous = {}, [], {}
    for row in ctx.rows(agent):
        version = row["version"]
        stored = ctx.read_version(agent, version)
        if stored is not None and service._roundtrip(stored, row) == "ok":
            nodes = list(stored.nodes.values())
        else:
            meta = RowMeta(row["id"], row["created_at"], row["created_by"], row["description"], row["is_active"])
            nodes = decompose_row(agent, ctx.config_hash, version, service._fields_of(row), meta=meta,
                                  inherited=service._inherited_for(ctx, agent, row), code_nodes=[], ltm_nodes=[],
                                  is_margin_account=ctx.is_margin_account).nodes
        children = {n.parent for n in nodes if n.parent}
        current = {}
        for node in nodes:
            if node.owner not in ("db", "default-file") or node.field not in COMPILED_FIELDS or _structural(node, children):
                continue
            digest = _sha(json.dumps([node.body, node.owner, node.node_type], ensure_ascii=False))
            key = node.id + ":" + digest[:16]
            current[node.id] = key
            item = revisions.setdefault(key, {
                "key": key, "id": node.id, "title": node.title, "body": node.body, "field": node.field,
                "node_type": node.node_type, "owner": node.owner, "parent": node.parent,
                "status": node.status, "tags": list(node.tags), "source_hash": digest,
                "versions": [], "first_version": version, "last_version": version,
            })
            item["versions"].append(version)
            item["last_version"] = version
        changes = {
            "added": sorted(i for i in current if i not in previous),
            "changed": sorted(i for i in current if i in previous and current[i] != previous[i]),
            "removed": sorted(i for i in previous if i not in current),
        }
        versions.append({"version": version, "created_at": service._iso(row["created_at"]),
                         "created_by": row["created_by"], "description": row["description"],
                         "is_active": row["is_active"], "changes": changes})
        previous = current
    if len(revisions) > MAX_LANDMARKS:
        raise service.BadRequest("Policy history exceeds the learning-map revision limit")
    return list(revisions.values()), versions


def lexical_vectors(texts):
    """Stable signed hashing, independent of the corpus and Python's hash seed."""
    out = np.zeros((len(texts), LEXICAL_DIM), dtype=float)
    for i, value in enumerate(texts):
        words = re.findall(r"[a-z][a-z0-9_-]{1,35}", value.lower())
        terms = words + [a + " " + b for a, b in zip(words, words[1:])]
        for term, count in Counter(terms).items():
            digest = hashlib.sha256(term.encode()).digest()
            col = int.from_bytes(digest[:4], "big") % LEXICAL_DIM
            out[i, col] += (1 if digest[4] & 1 else -1) * (1 + math.log(count))
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms > 0, norms, 1)


def fit_basis(vectors):
    vectors = np.asarray(vectors, dtype=float)
    if vectors.ndim != 2 or not vectors.shape[0] or not np.isfinite(vectors).all():
        raise ValueError("Invalid projection vectors")
    mean = vectors.mean(axis=0)
    centered = vectors - mean
    # eigh on the sample Gram matrix avoids an expensive d-by-d decomposition.
    values, left = np.linalg.eigh(centered @ centered.T)
    basis = []
    for idx in np.argsort(values)[::-1]:
        if values[idx] <= 1e-12 or len(basis) == 2:
            break
        axis = centered.T @ left[:, idx] / math.sqrt(values[idx])
        if axis[np.argmax(np.abs(axis))] < 0:
            axis = -axis
        basis.append(axis)
    while len(basis) < 2:
        axis = np.zeros(vectors.shape[1]); axis[len(basis) % vectors.shape[1]] = 1
        basis.append(axis)
    basis = np.asarray(basis)
    scale = np.maximum(np.std(centered @ basis.T, axis=0), 0.12)
    return {"mean": mean.tolist(), "basis": basis.tolist(), "scale": scale.tolist()}


def project(vectors, artifact):
    data = np.asarray(vectors, dtype=float)
    mean, basis = np.asarray(artifact["mean"]), np.asarray(artifact["basis"])
    scale = np.asarray(artifact["scale"])
    if data.ndim != 2 or data.shape[1] != len(mean) or basis.shape != (2, len(mean)) \
            or scale.shape != (2,) or not np.isfinite(data).all() or not np.isfinite(basis).all() \
            or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError("Projection dimensions or values do not match the frozen basis")
    return ((np.tanh(((data - mean) @ basis.T) / (2.5 * scale)) + 1) / 2).tolist()


@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        deadline = time.monotonic() + 8
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise service._store().StoreBusy()
                time.sleep(.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def projection(landmarks, path, *, embedder=None):
    """Cache coordinates; new revisions use the original basis, never a refit."""
    path = Path(path)
    with _locked(path):
        try:
            artifact = json.loads(path.read_text())
            if artifact.get("format") != FORMAT or artifact.get("method") not in ("semantic_pca", "lexical_pca"):
                raise ValueError("Unknown projection format")
            project(np.zeros((1, len(artifact["mean"]))), artifact)
        except (OSError, ValueError, KeyError, TypeError):
            artifact = None
        if not landmarks:
            return {"id": None, "method": "empty", "frozen": True, "note": "No versioned policy text yet."}
        pending = [n for n in landmarks if artifact is None or n["key"] not in artifact.get("points", {})]
        texts = ["search_document: " + n["body"] for n in pending]
        reason = ""
        vectors = None
        if pending and (artifact is None or artifact["method"] == "semantic_pca") and embedder is not None:
            if artifact is not None and getattr(embedder, "model", None) != artifact["embedding_model"]:
                reason = "Embedding model changed; new revisions await the original embedding model."
            else:
                try:
                    vectors = np.asarray(embedder.embed(texts, budget=5.0), dtype=float)
                    if vectors.ndim != 2 or len(vectors) != len(texts) or not np.isfinite(vectors).all():
                        raise ValueError("Invalid embedding answer")
                except Exception:
                    reason = "Local semantic embeddings unavailable."
        if artifact is None:
            method = "semantic_pca" if vectors is not None else "lexical_pca"
            if vectors is None:
                vectors = lexical_vectors(texts)
            # Earliest revision of each identity anchors the original landscape.
            first = {}
            for i, node in enumerate(pending):
                first.setdefault(node["id"], i)
            refs = [first[k] for k in sorted(first)]
            artifact = {"format": FORMAT, "method": method, "embedding_model":
                        getattr(embedder, "model", DEFAULT_EMBED_MODEL) if method == "semantic_pca" else "sha256-word-bigram-v1",
                        "reference_keys": [pending[i]["key"] for i in refs], "points": {}, **fit_basis(vectors[refs])}
            artifact["id"] = _sha(json.dumps({k: v for k, v in artifact.items() if k != "points"}, sort_keys=True))[:20]
        if pending and artifact["method"] == "lexical_pca":
            vectors = lexical_vectors(texts)
        if pending and vectors is not None:
            try:
                coords = project(vectors, artifact)
                artifact["points"].update({node["key"]: xy for node, xy in zip(pending, coords)})
            except ValueError:
                reason = "Embedding dimensions changed; new revisions await a compatible embedding model."
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(artifact, allow_nan=False))
        tmp.replace(path)
        for node in landmarks:
            point = artifact["points"].get(node["key"])
            node["x"], node["y"] = point if point else (None, None)
        semantic = artifact["method"] == "semantic_pca"
        return {"id": artifact["id"], "method": artifact["method"], "frozen": True,
                "embedding_model": artifact["embedding_model"], "reference_count": len(artifact["reference_keys"]),
                "pending": sum(n["x"] is None for n in landmarks),
                "note": ("Frozen local semantic projection." if semantic else "Frozen lexical projection; placement reflects shared words, not semantic embeddings.")
                        + " Axes describe text similarity, not risk or profitability. " + reason}


def _table_exists(engine, table):
    return inspect(engine).has_table(table)


def _evidence(engine, config_hash, *, days=90, limit=500):
    """A bounded citation audit; no account balances, raw prompts or raw replies."""
    if not _table_exists(engine, "decider_inputs"):
        return []
    from datetime import datetime, timedelta
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT id, run_id, prompt_version, decided_at, context_json, raw_reply
            FROM decider_inputs WHERE config_hash=:h AND call_kind='decide' AND decided_at >= :since
            ORDER BY decided_at DESC, id DESC LIMIT :lim"""),
                            {"h": config_hash, "since": datetime.now() - timedelta(days=days), "lim": limit}).fetchall()
    cases = []
    from .citations import split_cites
    for row in rows:
        item = dict(row._mapping)
        try:
            reply = json.loads(item["raw_reply"] or "{}")
            context = json.loads(item["context_json"] or "{}")
        except (ValueError, TypeError):
            continue
        decisions = reply.get("decisions", []) if isinstance(reply, dict) else reply if isinstance(reply, list) else []
        considered = reply.get("considered", []) if isinstance(reply, dict) else []
        context = context if isinstance(context, dict) else {}
        decisions = decisions if isinstance(decisions, list) else []
        considered = considered if isinstance(considered, list) else []
        for decision in decisions + considered:
            if not isinstance(decision, dict):
                continue
            ticker = str(decision.get("ticker") or "").upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
                continue
            reason = str(decision.get("reason") or decision.get("why") or "")
            _, inline = split_cites(reason)
            cited = decision.get("cited")
            cited = cited if isinstance(cited, list) else []
            cases.append({"id": f"input-{item['id']}-{len(cases)}", "input_id": item["id"],
                          "run_id": item["run_id"], "ticker": ticker, "observed_at": service._iso(item["decided_at"]),
                          "prompt_version": item["prompt_version"], "regime": context.get("regime"),
                          "action": str(decision.get("action") or decision.get("verdict") or "UNSPECIFIED").upper(),
                          "reason": reason[:1600], "signals": str(decision.get("signals") or "")[:1600],
                          "cited": sorted(set(str(i) for i in cited + list(inline))),
                          "coverage": "historical_decision_log", "eligible_for_recall": False, "outcomes": {}})
    return cases[:limit]


def learning_payload(engine, config_hash, agent, version=None, *, repo_root, is_margin_account=False,
                     days=90, embedder=None):
    service._check_agent(agent)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(config_hash)):
        raise service.BadRequest("Invalid configuration identifier")
    days = max(1, min(int(days), 3650))
    ctx = service._Ctx(engine, config_hash, repo_root, is_margin_account)
    selected = service._resolve_version(ctx, agent, version)
    ctx.row(agent, selected)
    landmarks, versions = history(ctx, agent)
    root = Path(repo_root) / "agents" / AGENT_DIR[agent] / "policy-router"
    if embedder is None:
        embedder = EmbeddingClient(cache=EmbedCache(root / "embed-cache.sqlite3"), timeout=3)
    projected = projection(landmarks, root / str(config_hash) / "learning-projection.json", embedder=embedder)
    try:
        reviews = [service._review_dict(r) for r in ctx.reviews(agent)]
    except Exception:
        reviews = []
    opportunities = {"cases": [], "metrics": {}, "metrics_by_horizon": {}}
    replays = {"runs": []}
    evidence = []
    if agent == "DeciderAgent":
        from . import opportunities as ledger
        from . import learning_replay
        if _table_exists(engine, "learning_opportunities"):
            opportunities = ledger.report(engine, config_hash, days=days, case_limit=500)
        else:
            opportunities["metrics_by_horizon"] = {str(h): ledger.metrics([], horizon=h) for h in (1, 3, 5)}
            opportunities["metrics"] = opportunities["metrics_by_horizon"]["3"]
        replays["runs"] = learning_replay.list_replays(engine, config_hash, limit=20)
        for index, replay in enumerate(replays["runs"][:5]):
            try:
                replays["runs"][index] = learning_replay.get_replay(engine, config_hash, replay["id"])
            except (learning_replay.ReplayError, ValueError):
                pass
        evidence = _evidence(engine, config_hash, days=days)
    from .themes import annotate as annotate_themes
    theme_catalog, theme_method = annotate_themes(
        landmarks, [opportunities.get("cases") or [], evidence], config_hash=config_hash)
    return {"schema_version": FORMAT, "agent": agent, "selected_version": selected,
            "projection": projected, "versions": versions, "landmarks": landmarks,
            "theme_catalog": theme_catalog, "theme_method": theme_method,
            "reviews": reviews, "evidence": evidence, "opportunities": opportunities, "replays": replays,
            "notes": ["Policy text comes from versioned prompt rows. Mutable long-term memory is excluded from historical landmarks.",
                      "Citation links are associations; they do not establish a rule's causal contribution to P&L.",
                      "Historical decision logs do not supply missed-opportunity outcomes. Prospective paper coverage begins after this update."]}
