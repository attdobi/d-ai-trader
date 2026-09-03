"""DB-facing service layer of the policy graph (routes.py and backfill.py call only this).

Every function takes `(engine, config_hash, …)` explicitly — nothing here reads config or the
environment. Reads go to prompt_versions / prompt_activation_events / prompt_change_reviews /
decider_memory / trade_outcomes; the only writes are the version directories under
`<repo_root>/agents/<dir>/policy-graph/<config_hash>/` via `policy_graph.store`.

Read-time materialization (`ensure_materialized`) is idempotent: the store returns `unchanged`
when the row bytes, builder version and overlays match what is on disk, so listing versions is
cheap after the first call. The row is canonical; the directory is a derived mirror.
"""
from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from . import BUILDER_VERSION
from . import code_blocks, health, inherited, lessons
from .compile import (
    bundle as compile_bundle, compile_effective, compile_runtime_preview, compile_stored, read_version_dir,
)
from .decompose import sha256_text
from .edges import derive_edges, resolve_link
from .model import (
    AGENT_DIR, AGENT_LABEL, AGENT_PREFIX, FIELDS, ID_RE, RowMeta, Version, actor_kind, version_stamp,
)

ATTRIBUTION_NOTE = ("Per-guideline trade attribution is not recorded yet — decisions do not cite "
                    "guideline ids; outcome figures are version-level.")
LTM_RECONSTRUCTED_NOTE = "rows as of today filtered by creation date — no row history exists"
INHERITED_FILENAME = {"soul": "SOUL.md", "memory": "MEMORY.md"}
LAYERS = ("effective", "stored")
MODES = ("stored", "effective", "runtime")


class NotFound(Exception):
    """Unknown agent / version / node (routes → 404)."""


class BadRequest(Exception):
    """Malformed parameters (routes → 400)."""


# ----------------------------------------------------------------------------- store / diff (concurrent track)
def _store():
    from . import store  # noqa: WPS433 — written by the store track; imported lazily so the
    return store          # package imports even while that module is still being built


def _diff():
    from . import diff
    return diff


def _iso(value) -> Optional[str]:
    return health.iso(value)


def _json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__float__") and not isinstance(value, (int, float, bool)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)
    return value


def _check_agent(agent_type: str) -> str:
    if agent_type not in AGENT_PREFIX:
        raise BadRequest(f"unknown agent_type {agent_type!r} (expected one of {', '.join(AGENT_PREFIX)})")
    return agent_type


def row_sha256(fields: dict) -> dict:
    """Per-field sha256 of the stored text (None for a NULL column) — the store's own function, so
    the stale check compares like with like."""
    return _store().source_sha256(fields)


def _same_sha(a: Optional[dict], b: dict) -> bool:
    if not isinstance(a, dict):
        return False
    empty = sha256_text("")
    for f in FIELDS:
        x, y = a.get(f), b.get(f)
        if x == y:
            continue
        if {x, y} <= {None, empty, ""}:      # a NULL column recorded either way
            continue
        return False
    return True


# ----------------------------------------------------------------------------- raw reads
def _rows(engine, config_hash: str, agent_type: str) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, agent_type, version, system_prompt, user_prompt_template, strategy_directives,
                   soul, memory, description, created_by, is_active, created_at
            FROM prompt_versions
            WHERE config_hash = :h AND agent_type = :a
            ORDER BY version ASC, id ASC
        """), {"h": config_hash, "a": agent_type}).fetchall()
    out = []
    seen = set()
    for r in rows:
        m = r._mapping
        v = int(m["version"])
        if v in seen:          # a duplicated version number: the newest row wins (highest id)
            out = [x for x in out if x["version"] != v]
        seen.add(v)
        out.append({
            "id": int(m["id"]), "agent_type": m["agent_type"], "version": v,
            "system_prompt": m["system_prompt"], "user_prompt_template": m["user_prompt_template"],
            "strategy_directives": m["strategy_directives"], "soul": m["soul"], "memory": m["memory"],
            "description": m["description"] or "", "created_by": m["created_by"] or "",
            "is_active": bool(m["is_active"]), "created_at": health.to_datetime(m["created_at"]),
        })
    out.sort(key=lambda x: x["version"])
    return out


def load_row(engine, config_hash: str, agent_type: str, version: int) -> Optional[dict]:
    """One prompt_versions row as a dict (None when absent)."""
    _check_agent(agent_type)
    for r in _rows(engine, config_hash, agent_type):
        if r["version"] == int(version):
            return r
    return None


def activation_events(engine, config_hash: str, agent_type: str) -> list:
    return health.load_activation_events(engine, config_hash, agent_type)


def reviews(engine, config_hash: str, agent_type: str) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, created_at, from_version, to_version, is_substantive, critic_verdict, critic_reason,
                   critic_confidence, critic_at, critic_auto, human_verdict, human_at, human_agrees_critic,
                   human_sections, realized_winrate_delta, realized_pnl, outcome_measured_at
            FROM prompt_change_reviews
            WHERE config_hash = :h AND agent_type = :a
            ORDER BY id ASC
        """), {"h": config_hash, "a": agent_type}).fetchall()
    return [dict(r._mapping) for r in rows]


def ltm_rows(engine, config_hash: str, *, as_of=None) -> list:
    """decider_memory rows (Postgres TEXT[] tags arrive as lists; SQLite stores a string literal)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, content, active, weight, tags, ticker, kind, source, created_at, updated_at
            FROM decider_memory
            WHERE config_hash = :h
            ORDER BY id ASC
        """), {"h": config_hash}).fetchall()
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    out = []
    cutoff = health.to_datetime(as_of) if as_of is not None else None
    for r in rows:
        m = dict(r._mapping)
        tags = m.get("tags")
        if dialect == "postgresql" and isinstance(tags, (list, tuple)):
            m["tags"] = [str(t) for t in tags]
        else:
            m["tags"] = lessons._tags(m)
        m["created_at"] = health.to_datetime(m.get("created_at"))
        m["updated_at"] = health.to_datetime(m.get("updated_at"))
        m["active"] = bool(m.get("active", True))
        if cutoff is not None and m["created_at"] is not None and m["created_at"] > cutoff:
            continue
        out.append(m)
    return out


# ----------------------------------------------------------------------------- lineage helpers
def _activation_for(events: list, version: int) -> Optional[dict]:
    for e in events:
        if e.get("to_version") == version:
            return {
                "event_id": e.get("id"), "created_at": _iso(e.get("created_at")), "action": e.get("action"),
                "actor": e.get("actor"), "from_version": e.get("from_version"), "batch_id": e.get("batch_id"),
                "reason": e.get("reason"),
            }
    return None


def _review_dict(r: dict) -> dict:
    return _json_safe({
        "review_id": r.get("id"), "created_at": _iso(r.get("created_at")),
        "from_version": r.get("from_version"), "to_version": r.get("to_version"),
        "critic_verdict": r.get("critic_verdict"), "critic_confidence": r.get("critic_confidence"),
        "critic_auto": r.get("critic_auto"), "critic_reason": r.get("critic_reason"),
        "human_verdict": r.get("human_verdict"), "human_sections": r.get("human_sections"),
        "human_agrees_critic": r.get("human_agrees_critic"),
        "realized_winrate_delta": r.get("realized_winrate_delta"), "realized_pnl": r.get("realized_pnl"),
        "outcome_measured_at": _iso(r.get("outcome_measured_at")),
    })


def _review_for(revs: list, version: int) -> Optional[dict]:
    hit = None
    for r in revs:
        if r.get("to_version") == version:
            hit = r                    # latest review wins
    return _review_dict(hit) if hit else None


def _rejected_for(revs: list, version: int) -> list:
    out = []
    for r in revs:
        if r.get("to_version") is None and r.get("from_version") == version:
            d = _review_dict(r)
            out.append({k: d[k] for k in ("review_id", "created_at", "critic_verdict", "critic_confidence",
                                          "critic_auto", "critic_reason", "human_verdict")})
    return out


def _parent_version(rows: list, version: int) -> Optional[int]:
    lower = [r["version"] for r in rows if r["version"] < version]
    return max(lower) if lower else None


def _lineage_version(rows: list, version: int) -> int:
    by_v = {r["version"]: r for r in rows}
    cur = version
    seen = set()
    while cur in by_v and cur not in seen:
        seen.add(cur)
        if actor_kind(by_v[cur]["created_by"]) != "weekly":
            return cur
        parent = _parent_version(rows, cur)
        if parent is None:
            return cur
        cur = parent
    return cur


def lineage_for(rows: list, events: list, revs: list, version: int) -> dict:
    return {
        "parent_version": _parent_version(rows, version),
        "lineage_version": _lineage_version(rows, version),
        "activation": _activation_for(events, version),
        "review": _review_for(revs, version),
    }


# ----------------------------------------------------------------------------- per-request context
class _Ctx:
    """Lazy caches for one request: rows/events/reviews per agent, ltm rows, git sha, overlays."""

    def __init__(self, engine, config_hash: str, repo_root, is_margin_account: bool, defaults_root=None):
        self.engine = engine
        self.config_hash = config_hash
        self.repo_root = Path(repo_root)
        # where inherited defaults (agents/<dir>/SOUL.default.md + git history) are resolved from;
        # normally the same checkout the version dirs are written into
        self.defaults_root = Path(defaults_root) if defaults_root else self.repo_root
        self.is_margin_account = bool(is_margin_account)
        self._rows: dict = {}
        self._events: dict = {}
        self._reviews: dict = {}
        self._ltm = None
        self._git_sha = None
        self.versions_cache: dict = {}
        self.read_errors: dict = {}      # (agent, version) -> message when a dir exists but cannot be read

    def rows(self, agent_type: str) -> list:
        if agent_type not in self._rows:
            self._rows[agent_type] = _rows(self.engine, self.config_hash, agent_type)
        return self._rows[agent_type]

    def events(self, agent_type: str) -> list:
        if agent_type not in self._events:
            self._events[agent_type] = activation_events(self.engine, self.config_hash, agent_type)
        return self._events[agent_type]

    def reviews(self, agent_type: str) -> list:
        if agent_type not in self._reviews:
            self._reviews[agent_type] = reviews(self.engine, self.config_hash, agent_type)
        return self._reviews[agent_type]

    def ltm(self) -> list:
        if self._ltm is None:
            self._ltm = ltm_rows(self.engine, self.config_hash)
        return self._ltm

    def git_sha(self) -> str:
        if self._git_sha is None:
            out = inherited._git(self.defaults_root, "rev-parse", "--short", "HEAD")
            self._git_sha = out.strip() if out else "worktree"
        return self._git_sha

    def root(self, agent_type: str) -> Path:
        return Path(_store().version_root(self.repo_root, agent_type, self.config_hash))

    def row(self, agent_type: str, version: int) -> dict:
        for r in self.rows(agent_type):
            if r["version"] == int(version):
                return r
        raise NotFound(f"{agent_type} v{version} not found for config {self.config_hash}")

    def current_version(self, agent_type: str) -> Optional[int]:
        active = [r["version"] for r in self.rows(agent_type) if r["is_active"]]
        return max(active) if active else None

    def latest_version(self, agent_type: str) -> Optional[int]:
        rows = self.rows(agent_type)
        return rows[-1]["version"] if rows else None

    def version_dir(self, agent_type: str, version: int) -> Path:
        return self.root(agent_type) / f"v{int(version)}"

    def read_version(self, agent_type: str, version: int) -> Optional[Version]:
        """Version from disk (cached per request); None when the dir is not materialized."""
        key = (agent_type, int(version))
        if key in self.versions_cache:
            return self.versions_cache[key]
        path = self.version_dir(agent_type, version)
        v = None
        self.read_errors.pop(key, None)
        if (path / "manifest.json").exists():
            try:
                v = read_version_dir(path)
            except Exception as exc:        # corrupt node file / sha mismatch / bad manifest
                self.read_errors[key] = f"{type(exc).__name__}: {exc}"
        self.versions_cache[key] = v
        return v

    def is_materialized(self, agent_type: str, version: int) -> bool:
        return (self.version_dir(agent_type, version) / "manifest.json").exists()

    def roundtrip(self, agent_type: str, version: int, row: dict) -> str:
        v = self.read_version(agent_type, version)
        if v is None and (agent_type, int(version)) in self.read_errors:
            return "mismatch"
        return _roundtrip(v, row)

    def forget(self, agent_type: str, version: int) -> None:
        self.versions_cache.pop((agent_type, int(version)), None)
        self.read_errors.pop((agent_type, int(version)), None)


def _fields_of(row: dict) -> dict:
    return {f: row[f] for f in FIELDS}


def _inherited_for(ctx: _Ctx, agent_type: str, row: dict) -> dict:
    out = {"soul": None, "memory": None}
    for f in ("soul", "memory"):
        if not row.get(f):
            out[f] = inherited.resolve_inherited(
                ctx.defaults_root, AGENT_DIR[agent_type], INHERITED_FILENAME[f], row["created_at"],
                is_active_row=bool(row["is_active"]))
    return out


def _ltm_for(ctx: _Ctx, agent_type: str, row: dict) -> tuple:
    """(sha12, nodes, snapshot, rows) — Decider only; empty for the other agents."""
    if agent_type != "DeciderAgent":
        return lessons.snapshot_sha([]), [], "none", []
    if row["is_active"]:
        rows, snapshot = ctx.ltm(), "live"
    else:
        cutoff = row["created_at"]
        rows = [r for r in ctx.ltm() if cutoff is None or r["created_at"] is None or r["created_at"] <= cutoff]
        snapshot = "reconstructed"
    sha, nodes = lessons.ltm_nodes(rows)
    return sha, nodes, snapshot, rows


def _materialize_kwargs(store, kwargs: dict) -> dict:
    """Only pass keyword arguments the store's materialize actually accepts (force is optional)."""
    try:
        params = inspect.signature(store.materialize).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def _ensure(ctx: _Ctx, agent_type: str, row: dict, *, materialized_by: str, force: bool = False) -> dict:
    """Materialize one row (no-op when unchanged). Raises store.StoreBusy / store.RoundTripError."""
    store = _store()
    version = row["version"]
    fields = _fields_of(row)
    meta = RowMeta(prompt_version_id=row["id"], created_at=row["created_at"], created_by=row["created_by"],
                   description=row["description"], is_active=row["is_active"])
    inh = _inherited_for(ctx, agent_type, row)
    cnodes = code_blocks.code_nodes(agent_type, fields, is_margin_account=ctx.is_margin_account)
    root = ctx.root(agent_type)
    # code/ltm overlay dirs (_code/<sha12>, _ltm/<sha12>) are content-addressed and written by
    # store.materialize itself via store.write_overlay_dir (once per sha, never rewritten).
    lsha, lnodes, snapshot, _lrows = _ltm_for(ctx, agent_type, row)
    lineage = lineage_for(ctx.rows(agent_type), ctx.events(agent_type), ctx.reviews(agent_type), version)
    if force:
        _drop_version_dir(store, root, version)
    kwargs = dict(
        meta=meta, inherited=inh, code_nodes=cnodes, code_sha=code_blocks.CODE_SHA, ltm_nodes=lnodes,
        ltm_sha=lsha, ltm_snapshot=snapshot, is_margin_account=ctx.is_margin_account,
        materialized_by=materialized_by, lineage=lineage, force=force,
    )
    res = store.materialize(ctx.repo_root, agent_type, ctx.config_hash, version, fields,
                            **_materialize_kwargs(store, kwargs))
    ctx.forget(agent_type, version)
    return {
        "agent_type": agent_type, "version": version, "action": getattr(res, "action", "unknown"),
        "path": str(getattr(res, "path", ctx.version_dir(agent_type, version))),
        "roundtrip": getattr(res, "roundtrip", "ok"),
    }


def _drop_version_dir(store, root: Path, version: int) -> None:
    """--force without store support: drop the manifest so the next materialize rebuilds.

    Only used when store.materialize has no `force` parameter; the store still takes its lock
    before writing, and a missing manifest is exactly the 'crashed between rename steps' state
    the store already recovers from."""
    try:
        params = inspect.signature(store.materialize).parameters
        if "force" in params:
            return
    except (TypeError, ValueError):
        pass
    manifest = root / f"v{int(version)}" / "manifest.json"
    if manifest.exists():
        manifest.unlink()


def _busy_exc(store):
    return getattr(store, "StoreBusy", ())


def ensure_materialized(engine, config_hash: str, agent_type: str, version: int, *, repo_root, is_margin_account: bool,
                        materialized_by: str = "dashboard", force: bool = False) -> dict:
    """Materialize one version (SELECT row → inherited defaults → code/ltm overlays → store)."""
    _check_agent(agent_type)
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    row = ctx.row(agent_type, version)
    return _ensure(ctx, agent_type, row, materialized_by=materialized_by, force=force)


def plan_action(ctx_or_engine, config_hash: str, agent_type: str, version: int, *, repo_root=None,
                is_margin_account: bool = False) -> str:
    """What materialize would do, without writing: created | unchanged | replaced | rebuilt."""
    ctx = ctx_or_engine if isinstance(ctx_or_engine, _Ctx) else _Ctx(ctx_or_engine, config_hash, repo_root, is_margin_account)
    row = ctx.row(agent_type, version)
    v = ctx.read_version(agent_type, version)
    if v is None:
        return "created"
    m = v.manifest
    if not _same_sha(m.get("source_sha256"), row_sha256(_fields_of(row))):
        return "replaced"
    if int(m.get("builder_version", -1)) != int(BUILDER_VERSION):
        return "rebuilt"
    if (m.get("code") or {}).get("sha") != code_blocks.CODE_SHA:
        return "rebuilt"
    lsha, _nodes, _snap, _rows_ = _ltm_for(ctx, agent_type, row)
    if agent_type == "DeciderAgent" and (m.get("ltm") or {}).get("sha") not in (lsha, None):
        return "rebuilt"
    inh = _inherited_for(ctx, agent_type, row)
    for f in ("soul", "memory"):
        fm = (m.get("fields") or {}).get(f) or {}
        want = sha256_text(inh[f].text) if (inh[f] is not None and not row.get(f)) else None
        if (fm.get("inherited_sha256") or None) != want:
            return "rebuilt"
    return "unchanged"


# ----------------------------------------------------------------------------- status helpers
def _roundtrip(v: Optional[Version], row: dict) -> str:
    if v is None:
        return "missing"
    try:
        compiled = compile_stored(v)
    except Exception:       # missing node, sha mismatch, malformed frontmatter
        return "mismatch"
    for f in FIELDS:
        a, b = compiled.get(f), row.get(f)
        if a == b or (a in (None, "") and b in (None, "")):
            continue
        return "mismatch"
    return "ok"


def _stale(v: Optional[Version], row: dict) -> bool:
    if v is None:
        return True
    return not _same_sha(v.manifest.get("source_sha256"), row_sha256(_fields_of(row)))


def _field_source(v: Optional[Version], row: dict, field: str) -> str:
    if v is not None:
        fm = (v.manifest.get("fields") or {}).get(field) or {}
        if fm.get("inherited"):
            return "inherited"
    return "stored" if row.get(field) else "inherited"


def _delta_of(vd) -> dict:
    if vd is None:
        return {"added": 0, "changed": 0, "removed": 0, "renamed": 0, "whitespace": 0, "source_changed": []}
    return {
        "added": len(getattr(vd, "added", []) or []),
        "changed": len(getattr(vd, "changed", []) or []),
        "removed": len(getattr(vd, "removed", []) or []),
        "renamed": len(getattr(vd, "renamed", []) or []),
        "whitespace": len(getattr(vd, "whitespace_only", []) or []),
        "source_changed": list(getattr(vd, "source_changed", []) or []),
    }


def _safe_diff(prev: Optional[Version], cur: Optional[Version]):
    if cur is None:
        return None
    try:
        return _diff().diff_versions(prev, cur)
    except Exception:
        return None


def _kind(prev: Optional[Version], cur: Optional[Version], row: dict, vd=None) -> str:
    history = len((cur.manifest.get("history") or [])) if cur is not None else 0
    if cur is not None:
        try:
            return _diff().version_kind(prev, cur, history, vd)
        except TypeError:
            try:
                return _diff().version_kind(prev, cur, history)
            except Exception:
                pass
        except Exception:
            pass
        if cur.manifest.get("kind"):
            return cur.manifest["kind"]
    if row["version"] == 0 or actor_kind(row["created_by"]) == "seed":
        return "seed"
    return "policy"


# ----------------------------------------------------------------------------- public: agents / versions
def list_agents(engine, config_hash: str, *, repo_root) -> dict:
    ctx = _Ctx(engine, config_hash, repo_root, False)
    agents = []
    for agent_type, prefix in AGENT_PREFIX.items():
        rows = ctx.rows(agent_type)
        stale = 0
        for r in rows:
            if _stale(ctx.read_version(agent_type, r["version"]), r):
                stale += 1
        agents.append({
            "agent_type": agent_type, "label": AGENT_LABEL[agent_type], "prefix": prefix,
            "active_version": ctx.current_version(agent_type), "latest_version": ctx.latest_version(agent_type),
            "version_count": len(rows), "stale": stale,
        })
    return {"config_hash": config_hash, "agents": agents}


def _materialize_all(ctx: _Ctx, agent_type: str, *, materialized_by: str) -> tuple:
    """Ensure every row; returns (results by version, busy flag, errors by version)."""
    store = _store()
    results, errors, busy = {}, {}, False
    for r in ctx.rows(agent_type):
        try:
            results[r["version"]] = _ensure(ctx, agent_type, r, materialized_by=materialized_by)
        except _busy_exc(store):
            busy = True
            break
        except Exception as exc:          # RoundTripError / IO — keep listing, flag the version
            errors[r["version"]] = f"{type(exc).__name__}: {exc}"
    return results, busy, errors


def list_versions(engine, config_hash: str, agent_type: str, *, repo_root, is_margin_account: bool,
                  materialize: bool = True, materialized_by: str = "dashboard") -> dict:
    _check_agent(agent_type)
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    rows = ctx.rows(agent_type)
    if not rows:
        raise NotFound(f"no prompt_versions rows for {agent_type} in config {config_hash}")
    results, busy, errors = ({}, False, {})
    if materialize:
        results, busy, errors = _materialize_all(ctx, agent_type, materialized_by=materialized_by)
    events, revs = ctx.events(agent_type), ctx.reviews(agent_type)
    outcomes = {}
    if agent_type == "DeciderAgent":
        spec = [{"version": r["version"], "created_at": r["created_at"], "is_active": r["is_active"],
                 "lineage_version": _lineage_version(rows, r["version"])} for r in rows]
        outcomes = health.version_window(engine, config_hash, spec, agent_type=agent_type, events=events)
    versions = []
    prev = None
    for r in rows:
        n = r["version"]
        cur = ctx.read_version(agent_type, n)
        if (agent_type, n) in ctx.read_errors:
            errors.setdefault(n, ctx.read_errors[(agent_type, n)])
        vd = _safe_diff(prev, cur)
        lin = lineage_for(rows, events, revs, n)
        item = {
            "version": n, "prompt_version_id": r["id"], "created_at": _iso(r["created_at"]),
            "created_by": r["created_by"], "actor_kind": actor_kind(r["created_by"]),
            "kind": _kind(prev, cur, r, vd), "description": r["description"], "is_active": r["is_active"],
            "parent_version": lin["parent_version"], "lineage_version": lin["lineage_version"],
            "activation": lin["activation"], "review": lin["review"],
            "rejected_candidates": _rejected_for(revs, n),
            "outcome": (outcomes.get(n) if agent_type == "DeciderAgent" else None),
            "fields": {f: _field_source(cur, r, f) for f in ("soul", "memory")},
            "materialized": ctx.is_materialized(agent_type, n), "stale": _stale(cur, r),
            "roundtrip": ctx.roundtrip(agent_type, n, r),
            "node_count": (len(cur.nodes) if cur is not None else 0),
            "delta_vs_prev": (_delta_of(vd) if vd is not None else
                              ((cur.manifest.get("delta_vs_prev") if cur is not None else None) or _delta_of(None))),
            "rewrites": (len(cur.manifest.get("history") or []) if cur is not None else 0),
            "materialize_action": (results.get(n) or {}).get("action"),
            "error": errors.get(n),
        }
        if agent_type != "DeciderAgent":
            item["outcome_reason"] = "no direct trade attribution"
        if item["delta_vs_prev"] is not None and "whitespace" not in item["delta_vs_prev"]:
            item["delta_vs_prev"]["whitespace"] = len(getattr(vd, "whitespace_only", []) or []) if vd else 0
        versions.append(item)
        prev = cur if cur is not None else prev
    notes = []
    if events:
        first = health.to_datetime(min((e["created_at"] for e in events if e.get("created_at")), default=None))
        if first is not None:
            notes.append(f"activation events exist from {first.date().isoformat()}; earlier versions show "
                         f"activation: not recorded")
    else:
        notes.append("no activation events recorded for this agent — windows fall back to row created_at")
    by_v = {r["version"]: r for r in rows}
    if 0 in by_v and 1 in by_v and by_v[0]["created_at"] and by_v[1]["created_at"] \
            and by_v[0]["created_at"] > by_v[1]["created_at"]:
        notes.append(f"v0 was rewritten on {by_v[0]['created_at'].date().isoformat()} — its created_at is later "
                     f"than v1; the timeline orders by version")
    if agent_type == "DeciderAgent":
        notes.append("long-term memory rows for historical versions are " + LTM_RECONSTRUCTED_NOTE)
    if busy:
        notes.append("policy graph is being rebuilt by another process — some versions may be stale")
    return {
        "agent_type": agent_type, "prefix": AGENT_PREFIX[agent_type], "config_hash": config_hash,
        "current": ctx.current_version(agent_type), "latest": ctx.latest_version(agent_type),
        "versions": versions, "notes": notes, "store_busy": busy,
    }


# ----------------------------------------------------------------------------- public: graph
def _resolve_version(ctx: _Ctx, agent_type: str, version) -> int:
    if version is None or version == "":
        cur = ctx.current_version(agent_type)
        if cur is None:
            cur = ctx.latest_version(agent_type)
        if cur is None:
            raise NotFound(f"no prompt_versions rows for {agent_type} in config {ctx.config_hash}")
        return cur
    try:
        return int(version)
    except (TypeError, ValueError):
        raise BadRequest(f"version must be an integer, got {version!r}")


def _ensure_and_read(ctx: _Ctx, agent_type: str, version: int, *, materialized_by: str) -> tuple:
    """(Version, materialize action, busy) — serves the existing dir when the store is busy."""
    store = _store()
    row = ctx.row(agent_type, version)
    action, busy = None, False
    try:
        action = _ensure(ctx, agent_type, row, materialized_by=materialized_by)["action"]
    except _busy_exc(store):
        busy = True
    v = ctx.read_version(agent_type, version)
    if v is None and not busy and (agent_type, int(version)) in ctx.read_errors:
        # self-heal: the dir exists but does not read back (corrupted by hand) → rebuild from the row
        action = _ensure(ctx, agent_type, row, materialized_by=materialized_by, force=True)["action"]
        v = ctx.read_version(agent_type, version)
    if v is None:
        if busy:
            raise store.StoreBusy("policy graph is being rebuilt — retry")
        err = ctx.read_errors.get((agent_type, int(version)))
        raise store.RoundTripError(f"{agent_type} v{version} could not be read back" + (f": {err}" if err else ""))
    return v, action, busy


def _change_flags(vd, cur: Version, prev: Optional[Version]) -> dict:
    """{id: (change, renamed_from)} for db/inherited nodes of `cur`."""
    flags: dict = {}
    if vd is None:
        base = "added" if prev is None else "same"
        return {i: (base, None) for i in cur.nodes}
    source_changed = set(getattr(vd, "source_changed", []) or [])
    renamed_to = {}
    for pair in getattr(vd, "renamed", []) or []:
        old, new = pair[0], pair[1]
        renamed_to[new] = old
    for i in getattr(vd, "same", []) or []:
        flags[i] = ("same", None)
    for i in getattr(vd, "whitespace_only", []) or []:
        flags[i] = ("whitespace", None)
    for i in getattr(vd, "changed", []) or []:
        flags[i] = ("changed", None)
    for i in getattr(vd, "added", []) or []:
        flags[i] = ("added", None)
    for new, old in renamed_to.items():
        flags[new] = ("renamed", old)
    per_node = getattr(vd, "per_node", None) or {}
    for i, nc in per_node.items():
        if isinstance(nc, dict):
            ch, rf = nc.get("change"), nc.get("renamed_from")
        else:
            ch = getattr(nc, "change", None)
            rf = getattr(nc, "renamed_from", None)
            if rf is None and ch == "renamed":
                rf = getattr(nc, "prev_id", None)
        if ch and i in cur.nodes:
            flags[i] = (ch, rf if rf is not None else flags.get(i, (None, None))[1])
    for i, n in cur.nodes.items():
        if n.field in source_changed and n.owner in ("db", "default-file"):
            flags[i] = ("source_changed", flags.get(i, (None, None))[1])
        elif i not in flags:
            flags[i] = (None, None)
    return flags


def _node_dict(n, *, prefix: str, by_id: dict, change=None, renamed_from=None, fires_map: Optional[dict] = None) -> dict:
    links = {}
    for target in n.links or []:
        try:
            links[target] = resolve_link(target, by_id, prefix=prefix)
        except Exception:
            links[target] = None
    inh = None
    if n.owner == "default-file":
        inh = {"from": n.extra.get("inherited_from"), "git_sha": n.extra.get("inherited_git_sha"),
               "resolution": n.extra.get("inherited_resolution")}
    fires = n.extra.get("fires") if n.owner == "code" else None
    status = n.status
    if n.owner == "code" and fires_map and n.id in fires_map:
        fires = bool(fires_map[n.id])
        status = "read-only" if fires else "inactive"
    return _json_safe({
        "id": n.id, "title": n.title, "node_type": n.node_type, "polarity": n.polarity,
        "polarity_source": n.polarity_source, "parent": n.parent, "field": n.field, "depth": n.depth,
        "owner": n.owner, "status": status, "compiled": n.compiled, "locked": bool(n.locked),
        "provenance": n.provenance, "order": n.order, "tags": list(n.tags), "tickers": list(n.tickers),
        "links": links, "body": n.body, "body_sha256": sha256_text(n.body), "sep_before": n.sep_before,
        "sep_after": n.sep_after, "change": change, "renamed_from": renamed_from,
        "condition": n.extra.get("condition") if n.owner == "code" else None,
        "fires": fires,
        "injected": n.extra.get("injected") if n.owner == "decider_memory" and n.node_type == "ltm" and n.parent else None,
        "inherited": inh,
        "meta": {k: v for k, v in (n.extra or {}).items()
                 if k not in ("inherited_from", "inherited_git_sha", "inherited_resolution", "condition", "fires")},
        "has_children": any(o.parent == n.id for o in by_id.values()),
    })


def _api_links(agent_type: str, version: int, config_hash: str) -> dict:
    base = f"/api/policy-graph/compiled?agent={agent_type}&version={version}"
    return {
        "compiled_stored": f"{base}&mode=stored&field=all",
        "compiled_effective": f"{base}&mode=effective&field=all",
        "runtime_preview": f"{base}&mode=runtime&field=all",
        "bundle": f"/api/policy-graph/bundle?agent={agent_type}&version={version}",
        "files": f"agents/{AGENT_DIR[agent_type]}/policy-graph/{config_hash}/v{version}/",
        "prompt_lab": f"/prompt-lab?agent={agent_type}&version={version}",
    }


def graph_payload(engine, config_hash: str, agent_type: str, version=None, *, repo_root, is_margin_account: bool,
                  layer: str = "effective", refs: bool = False, materialized_by: str = "dashboard") -> dict:
    _check_agent(agent_type)
    if layer not in LAYERS:
        raise BadRequest(f"layer must be one of {LAYERS}")
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    n = _resolve_version(ctx, agent_type, version)
    row = ctx.row(agent_type, n)
    rows = ctx.rows(agent_type)
    cur, action, busy = _ensure_and_read(ctx, agent_type, n, materialized_by=materialized_by)
    prefix = AGENT_PREFIX[agent_type]
    prev_n = _parent_version(rows, n)
    prev = None
    if prev_n is not None:
        try:
            prev, _a, _b = _ensure_and_read(ctx, agent_type, prev_n, materialized_by=materialized_by)
        except Exception:
            prev = ctx.read_version(agent_type, prev_n)
    vd = _safe_diff(prev, cur)
    flags = _change_flags(vd, cur, prev)

    nodes = dict(cur.nodes)
    edges = list(cur.edges)
    if refs:
        work = list(nodes.values())
        derived = derive_edges(work, version_stamp=version_stamp(agent_type, config_hash, n))
        for extra_node in work:
            if extra_node.id not in nodes:
                nodes[extra_node.id] = extra_node
        seen = {e.key() for e in edges}
        for e in derived:
            if e.key() not in seen and (e.edge_type == "cites" or e.target not in cur.nodes or e.source not in cur.nodes):
                seen.add(e.key())
                edges.append(e)
    else:
        nodes = {i: x for i, x in nodes.items() if x.node_type not in ("ticker", "concept")}
        edges = [e for e in edges if e.edge_type != "cites"]
    if layer == "stored":
        nodes = {i: x for i, x in nodes.items() if x.owner in ("db", "default-file", "generated") and x.node_type not in ("code", "ltm", "data")
                 and not i.startswith(prefix + ".code") and not i.startswith(prefix + ".ltm") and not i.startswith(prefix + ".runtime")}
        edges = [e for e in edges if e.edge_type not in ("includes", "overlaps", "constrains")]
    edges = [e for e in edges if e.source in nodes and e.target in nodes]

    fires_map = (cur.manifest.get("code") or {}).get("fires") or {}
    node_list = []
    for i, x in sorted(nodes.items(), key=lambda kv: (kv[1].depth, kv[1].order, kv[0])):
        ch, rf = flags.get(i, (None, None))
        node_list.append(_node_dict(x, prefix=prefix, by_id=nodes, change=ch, renamed_from=rf, fires_map=fires_map))
    edge_list = [{
        "source": e.source, "target": e.target, "edge_type": e.edge_type, "provenance": e.provenance,
        "via": e.via, "confidence": e.confidence,
        "synthetic": (nodes[e.source].node_type in ("ticker", "concept") or nodes[e.target].node_type in ("ticker", "concept")),
    } for e in edges]

    removed = []
    if vd is not None and prev is not None:
        for i in getattr(vd, "removed", []) or []:
            p = prev.nodes.get(i)
            if p is not None:
                removed.append({"id": i, "title": p.title, "node_type": p.node_type, "field": p.field, "parent": p.parent})
    delta = _delta_of(vd)
    stats = {**{k: delta[k] for k in ("added", "changed", "removed", "renamed", "whitespace")},
             "nodes": len(node_list), "edges": len(edge_list)}
    fm = cur.manifest.get("fields") or {}
    inh_payload = {}
    for f in ("soul", "memory"):
        meta = fm.get(f) or {}
        inh_payload[f] = ({"from": meta.get("inherited_from"), "git_sha": meta.get("inherited_git_sha"),
                           "resolution": meta.get("inherited_resolution"), "sha256": meta.get("inherited_sha256")}
                          if meta.get("inherited") else None)
    code_m = cur.manifest.get("code") or {}
    ltm_m = cur.manifest.get("ltm") or {}
    lin = lineage_for(rows, ctx.events(agent_type), ctx.reviews(agent_type), n)
    available = [r["version"] for r in rows]
    higher = [v for v in available if v > n]
    roundtrip = _roundtrip(cur, row)
    return _json_safe({
        "agent_type": agent_type, "prefix": prefix, "config_hash": config_hash, "version": n,
        "title": f"{AGENT_LABEL[agent_type]} policy v{n}", "root_id": cur.manifest.get("root_id") or f"{prefix}.root",
        "prompt_version_id": row["id"], "created_at": _iso(row["created_at"]), "created_by": row["created_by"],
        "actor_kind": actor_kind(row["created_by"]), "kind": _kind(prev, cur, row, vd), "description": row["description"],
        "is_active": row["is_active"], "current": ctx.current_version(agent_type),
        "previous_version": prev_n, "next_version": (min(higher) if higher else None),
        "available_versions": available, "layer": layer, "refs": bool(refs),
        "nodes": node_list, "edges": edge_list, "removed_nodes": removed, "stats": stats,
        "code": {"sha": code_m.get("sha"), "git_sha": code_m.get("git_sha"), "fires": fires_map},
        "ltm": {"sha": ltm_m.get("sha"), "snapshot": ltm_m.get("snapshot"),
                "count": len([x for x in cur.nodes.values() if x.node_type == "ltm" and x.parent == f"{prefix}.ltm"]),
                "injected_limit": ltm_m.get("injected_limit", lessons.DEFAULT_INJECTED_LIMIT),
                "note": (LTM_RECONSTRUCTED_NOTE if ltm_m.get("snapshot") == "reconstructed" else None)},
        "inherited": inh_payload,
        "timeline": {"activation": lin["activation"], "review": lin["review"], "parent_version": lin["parent_version"],
                     "lineage_version": lin["lineage_version"], "rejected_candidates": _rejected_for(ctx.reviews(agent_type), n)},
        "roundtrip": roundtrip, "stale": (_stale(cur, row) or busy), "store_busy": busy,
        "rebuilt_on_read": bool(action and action != "unchanged"), "materialize_action": action,
        "materialized_at": cur.manifest.get("materialized_at"), "builder_version": cur.manifest.get("builder_version"),
        "links": _api_links(agent_type, n, config_hash),
    })


# ----------------------------------------------------------------------------- public: node
def _all_versions(ctx: _Ctx, agent_type: str) -> list:
    out = []
    for r in ctx.rows(agent_type):
        v = ctx.read_version(agent_type, r["version"])
        if v is not None:
            out.append(v)
    return out


def _prev_node(vd, prev: Optional[Version], node_id: str):
    if prev is None:
        return None, None
    if node_id in prev.nodes:
        return prev.nodes[node_id], node_id
    for pair in (getattr(vd, "renamed", []) or []):
        if pair[1] == node_id and pair[0] in prev.nodes:
            return prev.nodes[pair[0]], pair[0]
    return None, None


def node_payload(engine, config_hash: str, agent_type: str, version, node_id: str, *, repo_root, is_margin_account: bool,
                 materialized_by: str = "dashboard") -> dict:
    _check_agent(agent_type)
    if not node_id or not ID_RE.match(node_id):
        raise BadRequest(f"invalid node id {node_id!r}")
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    n = _resolve_version(ctx, agent_type, version)
    row = ctx.row(agent_type, n)
    rows = ctx.rows(agent_type)
    cur, _action, _busy = _ensure_and_read(ctx, agent_type, n, materialized_by=materialized_by)
    if node_id not in cur.nodes:
        raise NotFound(f"node {node_id} not in {agent_type} v{n}")
    node = cur.nodes[node_id]
    prefix = AGENT_PREFIX[agent_type]
    prev_n = _parent_version(rows, n)
    prev = ctx.read_version(agent_type, prev_n) if prev_n is not None else None
    vd = _safe_diff(prev, cur)
    flags = _change_flags(vd, cur, prev)
    ch, rf = flags.get(node_id, (None, None))
    pnode, pid = _prev_node(vd, prev, node_id)
    diffmod = _diff()
    previous, udiff = None, None
    if pnode is not None:
        previous = {"version": prev_n, "id": pid, "body": pnode.body, "title": pnode.title}
        try:
            udiff = diffmod.node_unified_diff(pnode, node, prev_label=f"{pid}@v{prev_n}", cur_label=f"{node_id}@v{n}")
        except Exception:
            udiff = None
    elif prev is not None and node.owner in ("db", "default-file"):
        try:
            udiff = diffmod.node_unified_diff(None, node, prev_label=f"{node_id}@v{prev_n}", cur_label=f"{node_id}@v{n}")
        except Exception:
            udiff = None
    history = []
    if node.owner in ("db", "default-file"):
        try:
            history = list(diffmod.node_history(_all_versions(ctx, agent_type), node_id))
        except Exception:
            history = []
    hist = []
    for h in history:
        d = dict(h) if isinstance(h, dict) else {k: getattr(h, k, None) for k in ("version", "change", "body_sha256", "created_at", "actor_kind", "id")}
        d["created_at"] = _iso(d.get("created_at"))
        hist.append(d)
    present = [h for h in hist if h.get("change") not in ("removed", "absent", None) or h.get("body_sha256")]
    versions_present = sorted({int(h["version"]) for h in present if h.get("version") is not None})
    changed_in = sorted({int(h["version"]) for h in hist if h.get("change") in ("changed", "renamed", "added_changed")})
    outcome = None
    if agent_type == "DeciderAgent":
        spec = [{"version": r["version"], "created_at": r["created_at"], "is_active": r["is_active"],
                 "lineage_version": _lineage_version(rows, r["version"])} for r in rows]
        outcome = health.version_window(engine, config_hash, spec, agent_type=agent_type,
                                        events=ctx.events(agent_type)).get(n)
    overlaps = []
    for e in cur.edges:
        if e.edge_type != "overlaps":
            continue
        other = e.target if e.source == node_id else (e.source if e.target == node_id else None)
        if other and other in cur.nodes:
            overlaps.append({"id": other, "title": cur.nodes[other].title, "confidence": e.confidence,
                             "owner": cur.nodes[other].owner})
    overlaps.sort(key=lambda o: -(o["confidence"] or 0))
    fires_map = (cur.manifest.get("code") or {}).get("fires") or {}
    return _json_safe({
        "agent_type": agent_type, "version": n, "prompt_version_id": row["id"],
        "node": _node_dict(node, prefix=prefix, by_id=cur.nodes, change=ch, renamed_from=rf, fires_map=fires_map),
        "previous": previous, "diff_vs_previous": udiff, "history": hist,
        "first_seen": (versions_present[0] if versions_present else n),
        "present_in": (len(versions_present) if versions_present else 1),
        "changed_in": changed_in, "version_count": len(rows),
        "version_outcome": outcome, "overlaps": overlaps, "attribution_note": ATTRIBUTION_NOTE,
        "ltm_note": (LTM_RECONSTRUCTED_NOTE if (cur.manifest.get("ltm") or {}).get("snapshot") == "reconstructed"
                     and node.owner == "decider_memory" else None),
    })


# ----------------------------------------------------------------------------- public: diff
def _diff_stats(lines: list) -> dict:
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {"added": added, "removed": removed}


def diff_payload(engine, config_hash: str, agent_type: str, from_version, to_version, *, repo_root, is_margin_account: bool,
                 materialized_by: str = "dashboard") -> dict:
    _check_agent(agent_type)
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    try:
        a, b = int(from_version), int(to_version)
    except (TypeError, ValueError):
        raise BadRequest("from and to must be integers")
    prev, _x, _y = _ensure_and_read(ctx, agent_type, a, materialized_by=materialized_by)
    cur, _x, _y = _ensure_and_read(ctx, agent_type, b, materialized_by=materialized_by)
    diffmod = _diff()
    vd = diffmod.diff_versions(prev, cur)
    flags = _change_flags(vd, cur, prev)
    ratio = {}
    for pair in getattr(vd, "renamed", []) or []:
        ratio[pair[1]] = pair[2] if len(pair) > 2 else None
    nodes = []
    for i, (ch, rf) in sorted(flags.items()):
        if ch in (None, "same"):
            continue
        node = cur.nodes[i]
        pnode = prev.nodes.get(rf or i)
        lines = diffmod.node_unified_diff(pnode, node, prev_label=f"{rf or i}@v{a}", cur_label=f"{i}@v{b}")
        nodes.append({"id": i, "change": ch, "renamed_from": rf, "similarity": ratio.get(i), "field": node.field,
                      "title": node.title, "owner": node.owner, "diff": list(lines), "stats": _diff_stats(list(lines))})
    for i in getattr(vd, "removed", []) or []:
        pnode = prev.nodes.get(i)
        if pnode is None:
            continue
        lines = diffmod.node_unified_diff(pnode, None, prev_label=f"{i}@v{a}", cur_label=f"{i}@v{b}")
        nodes.append({"id": i, "change": "removed", "renamed_from": None, "similarity": None, "field": pnode.field,
                      "title": pnode.title, "owner": pnode.owner, "diff": list(lines), "stats": _diff_stats(list(lines))})
    sp, sc = compile_stored(prev), compile_stored(cur)
    ep, ec = compile_effective(prev), compile_effective(cur)
    source_changed = set(getattr(vd, "source_changed", []) or [])
    fields = {f: {"changed": (sp.get(f) != sc.get(f)), "effective_changed": (ep.get(f) != ec.get(f)),
                  "source_changed": f in source_changed} for f in FIELDS}
    delta = _delta_of(vd)
    return _json_safe({
        "agent_type": agent_type, "from": a, "to": b, "nodes": nodes, "fields": fields,
        "summary": {k: delta[k] for k in ("added", "changed", "removed", "renamed", "whitespace")},
    })


# ----------------------------------------------------------------------------- public: compiled text / bundle / file
def _header(agent_type: str, version: int, mode: str, field: str, body: str, note: str = "") -> str:
    label = {"stored": "stored render", "effective": "effective render", "runtime": "runtime preview"}[mode]
    n = len(body)
    extra = f" · {note}" if note else ""
    return f"# {agent_type} v{version} — {label} · {field} · {n:,} chars (~{n // 4:,} tokens){extra}\n---\n"


def compiled_text(engine, config_hash: str, agent_type: str, version, *, mode: str = "stored", field: str = "all",
                  repo_root, is_margin_account: bool, materialized_by: str = "dashboard") -> tuple:
    """(text, roundtrip) — mode=stored + one field: header + the exact column bytes."""
    _check_agent(agent_type)
    if mode not in MODES:
        raise BadRequest(f"mode must be one of {MODES}")
    if field != "all" and field not in FIELDS:
        raise BadRequest(f"field must be 'all' or one of {FIELDS}")
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    n = _resolve_version(ctx, agent_type, version)
    row = ctx.row(agent_type, n)
    cur, _a, _b = _ensure_and_read(ctx, agent_type, n, materialized_by=materialized_by)
    roundtrip = _roundtrip(cur, row)
    if mode == "runtime":
        preview = compile_runtime_preview(cur, is_margin_account=is_margin_account)
        body = (preview.get("system") or "") + "\n# ---- USER PROMPT ----\n" + (preview.get("user") or "")
        return _header(agent_type, n, mode, "system+user", body, preview.get("label", "")) + body, roundtrip
    values = compile_stored(cur) if mode == "stored" else compile_effective(cur)
    if field != "all":
        body = values.get(field)
        note = "stored NULL" if body is None else ""
        body = body or ""
        return _header(agent_type, n, mode, field, body, note) + body, roundtrip
    parts = []
    for f in FIELDS:
        parts.append(f"=== {f} ===\n" + (values.get(f) or ""))
    body = "\n\n".join(parts)
    return _header(agent_type, n, mode, "all", body) + body, roundtrip


def bundle_text(engine, config_hash: str, agent_type: str, version, *, repo_root, is_margin_account: bool,
                include_code: bool = True, include_ltm: bool = True, materialized_by: str = "dashboard") -> str:
    _check_agent(agent_type)
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    n = _resolve_version(ctx, agent_type, version)
    cur, _a, _b = _ensure_and_read(ctx, agent_type, n, materialized_by=materialized_by)
    return compile_bundle(cur, include_code=include_code, include_ltm=include_ltm)


def node_file(engine, config_hash: str, agent_type: str, version, node_id: str, *, repo_root, is_margin_account: bool,
              materialized_by: str = "dashboard") -> bytes:
    """Raw bytes of one node file (version dir first, then the linked overlay dirs)."""
    _check_agent(agent_type)
    if not node_id or not ID_RE.match(node_id):
        raise BadRequest(f"invalid node id {node_id!r}")
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    n = _resolve_version(ctx, agent_type, version)
    cur, _a, _b = _ensure_and_read(ctx, agent_type, n, materialized_by=materialized_by)
    candidates = [Path(cur.path)]
    for key in ("code", "ltm"):
        link = (cur.manifest.get(key) or {}).get("dir")
        if link:
            candidates.append((Path(cur.path) / link).resolve())
    for d in candidates:
        p = d / f"{node_id}.md"
        if p.is_file():
            return p.read_bytes()
    raise NotFound(f"node file {node_id}.md not found in {agent_type} v{n}")


# ----------------------------------------------------------------------------- public: rebuild
def rebuild(engine, config_hash: str, agent_type="all", version="all", *, repo_root, is_margin_account: bool,
            force: bool = False, materialized_by: str = "dashboard") -> dict:
    """Synchronous re-materialization; StoreBusy propagates (routes → 503)."""
    agents = list(AGENT_PREFIX) if agent_type in (None, "all") else [_check_agent(agent_type)]
    ctx = _Ctx(engine, config_hash, repo_root, is_margin_account)
    results = []
    ltm_sha = None
    for a in agents:
        rows = ctx.rows(a)
        if version not in (None, "all"):
            try:
                want = int(version)
            except (TypeError, ValueError):
                raise BadRequest(f"version must be an integer or 'all', got {version!r}")
            rows = [r for r in rows if r["version"] == want]
            if not rows:
                raise NotFound(f"{a} v{want} not found")
        for r in rows:
            try:
                res = _ensure(ctx, a, r, materialized_by=materialized_by, force=force)
                results.append({"agent_type": a, "version": r["version"], "action": res["action"], "roundtrip": res["roundtrip"]})
            except _busy_exc(_store()):
                raise
            except Exception as exc:
                results.append({"agent_type": a, "version": r["version"], "action": "error",
                                "error": f"{type(exc).__name__}: {exc}"})
            if a == "DeciderAgent" and r["is_active"]:
                ltm_sha = _ltm_for(ctx, a, r)[0]
    return {"results": results, "code_sha": code_blocks.CODE_SHA, "ltm_sha": ltm_sha, "config_hash": config_hash}


__all__ = [
    "NotFound", "BadRequest", "list_agents", "list_versions", "load_row", "ensure_materialized", "plan_action",
    "graph_payload", "node_payload", "diff_payload", "compiled_text", "bundle_text", "node_file", "rebuild",
    "ltm_rows", "activation_events", "reviews", "lineage_for", "row_sha256", "ATTRIBUTION_NOTE",
]
