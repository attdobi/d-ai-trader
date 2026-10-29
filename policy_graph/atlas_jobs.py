"""Explicit local atlas refresh jobs; browsing never submits work.

One worker serializes refreshes. At most four jobs are in flight globally and a
configuration/agent pair has at most one active job. The registry stores bounded
safe status DTOs, never engines, prompts, pixels or provider error messages.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
import uuid

MAX_IN_FLIGHT = 4
MAX_RETAINED = 48
RETENTION_S = 3600
_ACTIVE = {"queued", "running"}
_SCOPE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_JOB = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.RLock()
_jobs = {}
_pool = None


class AtlasJobError(ValueError):
    """Fixed request diagnostic, never a provider or driver exception."""


class AtlasJobBusy(AtlasJobError):
    """The bounded local queue has no free slot."""


class _RefreshError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public(job):
    return deepcopy({key:value for key,value in job.items() if key not in ("config_hash", "_created")})


def _prune(clock):
    terminal = sorted((job for job in _jobs.values() if job["status"] not in _ACTIVE),
                      key=lambda job:job["_created"])
    for job in terminal:
        if clock-job["_created"]>RETENTION_S or len(_jobs)>=MAX_RETAINED:
            _jobs.pop(job["id"],None)


def _small_result(value):
    """Only safe scalar projection/count metadata crosses the job boundary."""
    if not isinstance(value,dict):
        raise _RefreshError("invalid_refresh_result")
    out={"hosted_api_requests":0}
    for key in ("points", "pending", "reference_count", "point_limit", "policy_revisions", "source_records",
                "approximate_extensions", "local_embedding_requests"):
        found=value.get(key)
        if isinstance(found,int) and not isinstance(found,bool) and 0<=found<=10_000_000:
            out[key]=found
    ident=value.get("projection_id") or value.get("atlas_id") or value.get("id")
    if not isinstance(ident,str) or not re.fullmatch(r"[0-9a-f]{24}",ident) or value.get("method") not in ("semantic_tsne","semantic_pca_small"):
        raise _RefreshError("invalid_refresh_result")
    out["projection_id"]=ident
    out["atlas_id"]=ident
    out["method"]=value["method"]
    return out


def _refresh(engine, config_hash, agent, repo_root, *, is_margin_account=False, days=90):
    """Read immutable history + bounded observations, then extend frozen refs."""
    from . import service
    from .learning import history, _locked
    from .model import AGENT_DIR
    from .taxonomy import observation_inventory
    from .themes import annotate
    from .semantic_atlas import atlas_payload, _build_atlas
    from policy_router.embed import EmbedCache, EmbeddingClient, DEFAULT_EMBED_MODEL

    root=Path(repo_root)
    path=root/"agents"/AGENT_DIR[agent]/"policy-router"/config_hash/"semantic-atlas.json"
    ctx=service._Ctx(engine,config_hash,root,is_margin_account)
    landmarks,_=history(ctx,agent)
    inventory=observation_inventory(engine,config_hash,days=days,limit=120)
    if not inventory.get("available"):
        raise _RefreshError("source_inventory_unavailable")
    observations=inventory.get("observations") or []
    annotate(landmarks,[],config_hash=config_hash,observations=observations,
             observation_counts=inventory.get("topic_counts") or {})
    cache=root/"agents"/"decider"/"policy-router"/"embed-cache.sqlite3"
    # Both the destination and model are fixed local implementation choices,
    # never caller-controlled URLs, credentials or provider fallbacks.
    embedder=EmbeddingClient("http://127.0.0.1:1234/v1",DEFAULT_EMBED_MODEL,
                             cache=EmbedCache(cache),timeout=15)
    with _locked(path):
        existing=atlas_payload([],[],path,config_hash=config_hash,agent=agent)
        if existing["method"] not in ("semantic_tsne","semantic_pca_small"):
            raise _RefreshError("semantic_atlas_not_built")
        # Hold the same lock used by the public build wrapper, then call its
        # implementation. A disappearing/corrupt artifact cannot silently turn
        # this extension-only action into a new t-SNE reference fit.
        result=_build_atlas(landmarks,observations,path,config_hash=config_hash,agent=agent,
                            embedder=embedder,force=False,allow_lexical=False,
                            embedding_budget_s=60,max_points=existing.get("point_limit",700))
    return {"projection_id":result["id"],"method":result["method"],"points":len(result["points"]),
            "pending":result["pending"],"reference_count":result["reference_count"],
            "point_limit":result.get("point_limit",700),"policy_revisions":len(landmarks),
            "source_records":len(observations),"local_embedding_requests":embedder.calls,
            "approximate_extensions":sum(point.get("placement")=="knn_extension_approximate" for point in result["points"])}


def _run(job_id, engine, config_hash, agent, repo_root, is_margin_account, days, worker):
    with _lock:
        job=_jobs[job_id]
        job.update(status="running",started_at=_now())
    try:
        result=worker(engine,config_hash,agent,repo_root,is_margin_account=is_margin_account,days=days)
        result=_small_result(result)
        with _lock:
            _jobs[job_id].update(status="complete",finished_at=_now(),result=result)
    except Exception as exc:
        known={"source_inventory_unavailable","semantic_atlas_not_built","invalid_refresh_result"}
        code=str(exc) if isinstance(exc,_RefreshError) and str(exc) in known else "local_atlas_refresh_failed"
        with _lock:
            _jobs[job_id].update(status="error",finished_at=_now(),error_code=code,
                                 error="Local atlas refresh did not complete; provider and connection diagnostics withheld.")


def submit(engine, config_hash, agent, repo_root, *, is_margin_account=False, days=90, worker=None):
    """Submit an explicit refresh, or return the same already-active scoped job.

    ``worker`` is an injected local function for tests. Production callers omit
    it. It receives the same explicit scoped inputs as ``_refresh``.
    """
    from .model import AGENT_DIR
    if not isinstance(config_hash,str) or not _SCOPE.fullmatch(config_hash):
        raise AtlasJobError("invalid_configuration")
    if not isinstance(agent,str) or agent not in AGENT_DIR:
        raise AtlasJobError("invalid_agent")
    if not isinstance(days,int) or isinstance(days,bool) or not 1<=days<=3650:
        raise AtlasJobError("invalid_days")
    if not isinstance(is_margin_account,bool):
        raise AtlasJobError("invalid_account_mode")
    try:
        root=Path(repo_root).resolve()
    except (TypeError,ValueError,OSError):
        raise AtlasJobError("invalid_repository_root") from None
    global _pool
    with _lock:
        _prune(time.monotonic())
        existing=next((job for job in _jobs.values() if job["config_hash"]==config_hash
                       and job["agent"]==agent and job["status"] in _ACTIVE),None)
        if existing is not None:
            return _public(existing)
        if sum(job["status"] in _ACTIVE for job in _jobs.values())>=MAX_IN_FLIGHT:
            raise AtlasJobBusy("atlas_queue_full")
        ident=uuid.uuid4().hex
        _jobs[ident]={"id":ident,"job_id":ident,"config_hash":config_hash,"agent":agent,"days":days,
                      "status":"queued","created_at":_now(),"started_at":None,"finished_at":None,
                      "_created":time.monotonic()}
        if _pool is None:
            _pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="semantic-atlas")
        try:
            _pool.submit(_run,ident,engine,config_hash,agent,root,is_margin_account,days,worker or _refresh)
        except Exception:
            _jobs[ident].update(status="error",finished_at=_now(),error_code="atlas_worker_unavailable",
                                error="The local atlas worker is unavailable.")
        return _public(_jobs[ident])


def get(job_id, config_hash):
    """Return one safe scoped snapshot. No source, model or file access occurs."""
    if not isinstance(job_id,str) or not _JOB.fullmatch(job_id) or not isinstance(config_hash,str):
        return None
    with _lock:
        _prune(time.monotonic())
        job=_jobs.get(job_id)
        if job is None or job["config_hash"]!=config_hash:
            return None
        return _public(job)


__all__=["AtlasJobError","AtlasJobBusy","MAX_IN_FLIGHT","submit","get"]
