"""Frozen local text-embedding neighborhoods for an interactive learning atlas.

Building is explicit and bounded. Reading never embeds, fits or imports sklearn.
The old learning-projection.json remains untouched. Taxonomy labels annotate the
result; they never supply target coordinates or artificial cluster assignments.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

import numpy as np

FORMAT = 1
MAX_POINTS = 700
SEED = 42
MODEL_LEXICAL = "sha256-word-bigram-v1"
SETTINGS = {"algorithm": "tsne", "seed": SEED, "max_iter": 1000,
            "metric": "cosine", "initialization": "pca", "learning_rate": "auto",
            "neighbor_extension": "cosine_knn_barycenter_v1", "cluster_algorithm": "kmeans"}
_SCOPE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SECRET = re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}|\bAuthorization\s*:\s*Bearer\s+\S+|\bdata:|\b(?:postgres(?:ql)?|mysql)://\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)


class AtlasUnavailable(ValueError):
    """A fixed local diagnostic; provider/driver exceptions are never displayed."""


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _safe_text(value, limit=24000):
    if not isinstance(value, str) or _SECRET.search(value):
        return ""
    return value[:limit]


def _scope(config_hash, agent):
    from .model import AGENT_DIR
    if not isinstance(config_hash, str) or not _SCOPE.fullmatch(config_hash) or agent not in AGENT_DIR:
        raise AtlasUnavailable("invalid_atlas_scope")


def source_points(landmarks, observations):
    """Bounded public source DTOs; no prompts, accounts, URLs or image payloads.

    Saved news remains dated window context. Its date does not become an older
    policy version's decision-time evidence just because both share this atlas.
    """
    points, seen = [], set()
    for row in landmarks or ():
        if not isinstance(row, dict):
            continue
        key, ident, body = row.get("key"), row.get("id"), _safe_text(row.get("body"))
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not isinstance(ident, str) or not body or key in seen:
            continue
        versions = [v for v in row.get("versions", []) if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
        public = {"key":key, "source_key":key, "id":ident, "kind":"guideline",
                  "title":_safe_text(row.get("title"), 180) or ident, "body":body,
                  "versions":versions, "source_hash":row.get("source_hash") or hashlib.sha256(body.encode()).hexdigest()}
        for field in ("field", "node_type", "owner", "parent", "status", "first_version", "last_version",
                      "tags", "market_themes", "direct_market_themes", "linked_market_themes", "theme_evidence"):
            if field in row:
                public[field] = row[field]
        public["embedding_text_sha256"] = hashlib.sha256(("search_document: " + body)[:3000].encode()).hexdigest()
        points.append(public); seen.add(key)
    for row in observations or ():
        if not isinstance(row, dict) or row.get("source_kind") not in ("news_observation", "feedback_hypothesis"):
            continue
        ident, body = row.get("record_id"), _safe_text(row.get("text"), 6000)
        if not isinstance(ident, str) or not re.fullmatch(r"(?:summary|feedback):\d{1,20}", ident) or not body:
            continue
        digest = hashlib.sha256(body.encode()).hexdigest()
        # Content changes create a new source revision even if a mutable source
        # row was edited. Do not silently reuse a coordinate for changed text.
        key = ident + ":" + digest[:16]
        if key in seen:
            continue
        public = {"key":key, "source_key":ident, "id":ident, "record_id":ident,
                  "kind":row["source_kind"], "title":body.splitlines()[0][:160], "body":body,
                  "text":body, "versions":[], "source_hash":digest,
                  "source_agent":_safe_text(row.get("source_agent"), 100),
                  "observed_at":_safe_text(row.get("observed_at"), 80),
                  "claim_status":row.get("claim_status", "recorded_report_not_independently_verified")}
        for field in ("market_themes", "theme_evidence"):
            if field in row:
                public[field] = row[field]
        public["embedding_text_sha256"] = hashlib.sha256(embedding_text(public).encode()).hexdigest()
        points.append(public); seen.add(key)
    return points


def embedding_text(point):
    body = point["body"]
    if point["kind"] == "guideline":
        return ("search_document: " + body)[:3000]
    # Article headlines carry source-specific content. Repeated technical field
    # checklists/not_shown boilerplate should not dominate news neighborhoods.
    lines = body.splitlines()
    heads = [line for line in lines[:6] if line.lstrip().startswith("[")]
    if heads:
        body = "\n".join(heads[:3])
    else:
        body = body[:1800]
    return ("search_document: " + body)[:3000]


def _unit(vectors):
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or not values.shape[1] or not np.isfinite(values).all():
        raise AtlasUnavailable("invalid_atlas_vectors")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms <= 1e-10):
        raise AtlasUnavailable("empty_atlas_vector")
    return values / norms


def _fit(vectors):
    """Actual seeded nonlinear projection and embedding-space clustering."""
    try:
        from sklearn.manifold import TSNE
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA
    except ImportError:
        raise AtlasUnavailable("atlas_projection_dependency_unavailable") from None
    values = _unit(vectors)
    n = len(values)
    if n < 4:
        centered = values - values.mean(axis=0)
        _, _, basis = np.linalg.svd(centered, full_matrices=False)
        coords = centered @ basis[:2].T
        if coords.shape[1] < 2:
            coords = np.pad(coords, ((0,0),(0,2-coords.shape[1])))
        labels = np.zeros(n, dtype=int)
        return coords, labels, {"projection_algorithm":"small_corpus_pca", "perplexity":None, "kl_divergence":None}
    # Retain high-dimensional semantic neighborhoods with deterministic PCA
    # preconditioning. This reduces fit time without involving taxonomy labels.
    reduced = PCA(n_components=min(50,n-1,values.shape[1]), random_state=SEED).fit_transform(values)
    perplexity = min(30.0, max(2.0, (n-1)/3))
    fit = TSNE(n_components=2, perplexity=perplexity, metric="cosine", init="pca",
               random_state=SEED, learning_rate="auto", max_iter=1000,
               method="barnes_hut", n_jobs=1)
    coords = fit.fit_transform(reduced)
    cluster_count = min(10, max(2, round(math.sqrt(n/6))), len(np.unique(values, axis=0)))
    labels = KMeans(n_clusters=cluster_count, random_state=SEED, n_init=10).fit_predict(values)
    return coords, labels, {"projection_algorithm":"tsne", "perplexity":perplexity,
                            "kl_divergence":float(fit.kl_divergence_)}


def _normalize(coords):
    coords = np.asarray(coords, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 2 or not np.isfinite(coords).all():
        raise AtlasUnavailable("invalid_atlas_coordinates")
    low, high = coords.min(axis=0), coords.max(axis=0)
    scaled = .06 + .88*(coords-low)/np.maximum(high-low, 1e-8)
    scaled[:,high-low<=1e-8] = .5
    return scaled.tolist()


def _neighbors(artifact):
    keys = sorted(artifact["points"])
    vectors = _unit([artifact["points"][key]["vector"] for key in keys])
    similarity = vectors @ vectors.T
    for index,key in enumerate(keys):
        nearest = sorted(((float(similarity[index,j]),other) for j,other in enumerate(keys) if j!=index),
                         key=lambda pair:(-pair[0],pair[1]))[:6]
        artifact["points"][key]["neighbors"] = [{"key":other,"similarity":round(max(-1,min(1,score)),6)} for score,other in nearest]


def _read(path, config_hash, agent):
    try:
        path = Path(path)
        if path.stat().st_size > 32_000_000:
            return None
        artifact = json.loads(path.read_text())
        if (artifact.get("format") != FORMAT or artifact.get("config_hash") != config_hash
                or artifact.get("agent") != agent or artifact.get("settings") != SETTINGS
                or artifact.get("method") not in ("semantic_tsne","lexical_tsne","semantic_pca_small","lexical_pca_small")
                or not re.fullmatch(r"[0-9a-f]{24}",str(artifact.get("id")))
                or not isinstance(artifact.get("points"), dict) or not 1 <= len(artifact["points"]) <= MAX_POINTS):
            return None
        dimensions=set()
        for point in artifact["points"].values():
            if not isinstance(point, dict) or not isinstance(point.get("xy"), list) or len(point["xy"]) != 2 \
                    or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1 for v in point["xy"]):
                return None
            vector=point.get("vector")
            if (not isinstance(vector,list) or not 1<=len(vector)<=4096
                    or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vector)
                    or sum(abs(v) for v in vector)<=1e-10
                    or not re.fullmatch(r"cluster_\d{1,4}",str(point.get("cluster_id")))
                    or not re.fullmatch(r"[0-9a-f]{64}",str(point.get("text_sha256")))):
                return None
            dimensions.add(len(vector))
        if len(dimensions)!=1:
            return None
        return artifact
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _public(points, artifact, *, unavailable_reason=None):
    joined, pending = [], 0
    saved = artifact.get("points", {}) if artifact else {}
    for source in points:
        record = saved.get(source["key"])
        if record and record.get("text_sha256") == source["embedding_text_sha256"]:
            joined.append({**source,"x":record["xy"][0],"y":record["xy"][1],
                           "cluster_id":record.get("cluster_id"),"placement":record.get("placement","tsne_reference"),
                           "neighbors":record.get("neighbors",[]) if isinstance(record.get("neighbors"),list) else []})
        else:
            pending += 1
    visible = {point["key"] for point in joined}
    for point in joined:
        point["neighbors"] = [row for row in point["neighbors"] if isinstance(row,dict) and row.get("key") in visible
                              and isinstance(row.get("similarity"),(int,float)) and not isinstance(row["similarity"],bool)
                              and math.isfinite(row["similarity"]) and -1<=row["similarity"]<=1]
    clusters = []
    for ident in sorted({p["cluster_id"] for p in joined if p.get("cluster_id") is not None}):
        members = [p for p in joined if p.get("cluster_id") == ident]
        clusters.append({"id":ident,"member_keys":[p["key"] for p in members],"count":len(members),
                         "x":float(np.mean([p["x"] for p in members])),"y":float(np.mean([p["y"] for p in members])),
                         "kind_counts":dict(Counter(p["kind"] for p in members))})
    method = artifact.get("method") if artifact else "unavailable"
    return {"id":artifact.get("id") if artifact else None,"method":method,
            "embedding_model":artifact.get("embedding_model") if artifact else None,
            "frozen":True,"points":joined,"clusters":clusters,"pending":pending,
            "reference_count":artifact.get("reference_count",0) if artifact else 0,
            "point_limit":artifact.get("point_limit",MAX_POINTS) if artifact else MAX_POINTS,
            "created_at":artifact.get("created_at") if artifact else None,
            "fitted_with":artifact.get("fitted_with") if artifact else None,
            "note": ("Frozen local semantic t-SNE neighborhoods." if method=="semantic_tsne" else
                     "Frozen lexical t-SNE neighborhoods; these are word features, not semantic embeddings." if method=="lexical_tsne" else
                     "Small-corpus PCA of local semantic embeddings; fewer than four source points cannot support the configured t-SNE fit." if method=="semantic_pca_small" else
                     "Small-corpus PCA of lexical word features, not semantic embeddings." if method=="lexical_pca_small" else
                     "Atlas has not been built. Use the explicit local build command.") +
                    " Topic labels annotate the actual projected neighborhoods. Distances, density and colors are descriptive, not trading quality or a decision boundary. " + (unavailable_reason or ""),
            "source_context_note":"News and feedback retain their own observation dates; they are window context, not evidence retrospectively available to older policy versions."}


def atlas_payload(landmarks, observations, path, *, config_hash, agent):
    """Fast read only. No local or hosted inference, fitting or cache mutation."""
    _scope(config_hash,agent)
    return _public(source_points(landmarks,observations), _read(path,config_hash,agent))


def build_atlas(landmarks, observations, path, *, config_hash, agent, embedder=None,
                force=False, allow_lexical=False, embedding_budget_s=60.0, max_points=MAX_POINTS):
    from .learning import _locked
    _scope(config_hash,agent)
    with _locked(Path(path)):
        return _build_atlas(landmarks,observations,path,config_hash=config_hash,agent=agent,
                            embedder=embedder,force=force,allow_lexical=allow_lexical,
                            embedding_budget_s=embedding_budget_s,max_points=max_points)


def _build_atlas(landmarks, observations, path, *, config_hash, agent, embedder=None,
                 force=False, allow_lexical=False, embedding_budget_s=60.0, max_points=MAX_POINTS):
    """Explicit bounded build. Existing coordinates stay frozen unless force=True.

    t-SNE has no native transform. New revisions use a declared cosine-neighbor
    barycenter approximation against frozen reference vectors, never a hidden
    re-fit. ``force`` creates a new atlas identity and intentionally re-fits.
    """
    _scope(config_hash,agent)
    if not isinstance(embedding_budget_s,(int,float)) or not 0<float(embedding_budget_s)<=120:
        raise AtlasUnavailable("invalid_embedding_budget")
    if not isinstance(max_points,int) or isinstance(max_points,bool) or not 1<=max_points<=MAX_POINTS:
        raise AtlasUnavailable("invalid_atlas_point_limit")
    sources = source_points(landmarks,observations)
    if not sources:
        return _public([],None)
    path = Path(path)
    existing = None if force else _read(path,config_hash,agent)
    if existing and any(p["key"] in existing["points"] and existing["points"][p["key"]].get("text_sha256") != p["embedding_text_sha256"] for p in sources):
        raise AtlasUnavailable("immutable_atlas_source_key_changed")
    pending = [p for p in sources if existing is None or p["key"] not in existing["points"]
               or existing["points"][p["key"]].get("text_sha256") != p["embedding_text_sha256"]]
    if existing and not pending:
        return _public(sources,existing)
    if existing and len(existing["points"])>max_points:
        raise AtlasUnavailable("smaller_point_cap_requires_explicit_refit")
    room = max_points - (len(existing["points"]) if existing else 0)
    if room <= 0:
        return _public(sources,existing,unavailable_reason="The frozen atlas reached its point cap; an explicit refit is required for new records.")
    pending = pending[:room]
    texts = [embedding_text(p) for p in pending]
    if embedder is not None:
        base = getattr(embedder,"base_url",None)
        if base is not None:
            parsed=urlsplit(base)
            if parsed.scheme not in ("http","https") or parsed.hostname not in ("127.0.0.1","localhost","::1") or parsed.username or parsed.password:
                raise AtlasUnavailable("atlas_requires_loopback_embeddings")
    model = getattr(embedder,"model",None)
    vectors = None
    if existing and existing["method"].startswith("lexical"):
        from .learning import lexical_vectors
        vectors = lexical_vectors(texts); model=MODEL_LEXICAL
    else:
        if existing and existing["embedding_model"] != model:
            raise AtlasUnavailable("atlas_embedding_model_changed_explicit_refit_required")
        if embedder is not None:
            try:
                vectors = _unit(embedder.embed(texts,budget=float(embedding_budget_s)))
            except Exception:
                if existing or not allow_lexical:
                    raise AtlasUnavailable("local_semantic_embeddings_unavailable") from None
        if vectors is None:
            if not allow_lexical:
                raise AtlasUnavailable("local_semantic_embeddings_unavailable")
            from .learning import lexical_vectors
            vectors = lexical_vectors(texts); model=MODEL_LEXICAL
    vectors = _unit(vectors)
    if len(vectors)!=len(pending):
        raise AtlasUnavailable("atlas_vector_count_mismatch")
    if existing:
        # Vectors are JSON numeric arrays inside the ignored local artifact;
        # no executable deserialization or network fallback is involved.
        refs=[point for point in existing["points"].values() if point.get("placement") != "knn_extension_approximate"]
        reference_vectors=_unit([p["vector"] for p in refs])
        if vectors.shape[1]!=reference_vectors.shape[1]:
            raise AtlasUnavailable("atlas_embedding_dimensions_changed")
        coordinates=[];labels=[]
        for vector in vectors:
            distances=np.maximum(0,1-reference_vectors@vector)
            indices=np.argsort(distances,kind="stable")[:min(5,len(refs))]
            weights=1/np.maximum(distances[indices],1e-5)**2;weights/=weights.sum()
            coordinates.append(np.sum(np.asarray([refs[i]["xy"] for i in indices])*weights[:,None],axis=0).tolist())
            labels.append(refs[int(indices[0])]["cluster_id"])
        artifact=existing
        placement="knn_extension_approximate"
    else:
        raw, labels, fitted = _fit(vectors)
        coordinates=_normalize(raw)
        method=("lexical_" if model==MODEL_LEXICAL else "semantic_") + ("tsne" if fitted["projection_algorithm"]=="tsne" else "pca_small")
        artifact={"format":FORMAT,"config_hash":config_hash,"agent":agent,"settings":SETTINGS,
                  "method":method,"embedding_model":model,"reference_count":len(pending),
                  "created_at":datetime.now(timezone.utc).isoformat(),"points":{},"fitted_with":fitted,"point_limit":max_points}
        artifact["id"]=_hash({"scope":[config_hash,agent],"model":model,"settings":SETTINGS,
                              "sources":[[p["key"],p["embedding_text_sha256"]] for p in pending]})[:24]
        placement="tsne_reference" if fitted["projection_algorithm"]=="tsne" else "small_corpus_pca"
    for point,vector,xy,label in zip(pending,vectors,coordinates,labels):
        artifact["points"][point["key"]]={"xy":xy,"vector":vector.tolist(),"text_sha256":point["embedding_text_sha256"],
                                           "cluster_id":"cluster_"+str(int(label)) if isinstance(label,(int,np.integer)) else label,
                                           "placement":placement}
    _neighbors(artifact)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(".part")
    serialized=json.dumps(artifact,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(serialized.encode())>32_000_000:
        raise AtlasUnavailable("atlas_artifact_size_exceeded")
    temporary.write_text(serialized)
    temporary.replace(path)
    return _public(sources,artifact)


__all__=["AtlasUnavailable","MAX_POINTS","SETTINGS","source_points","embedding_text","atlas_payload","build_atlas"]
