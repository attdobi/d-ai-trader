"""On-disk store for materialized policy-graph versions (spec section 5).

Layout under version_root(repo_root, agent_type, config_hash)
(= repo_root/agents/<dir>/policy-graph/<config_hash>):

  .lock                       flock file (every writer holds it; never proceed unlocked)
  v<N>/                       <id>.md node files + edges.json + manifest.json
  _code/<sha12>/              content-addressed copies of the code-owned nodes (never rewritten)
  _ltm/<sha12>/               content-addressed decider_memory snapshot (never rewritten)
  _prior/v<N>-<sha8>/         previous contents of a version number whose ROW bytes changed
  _pending/v<N>-<proposal>/   Phase-2 staged dir adopted when its compile equals the row bytes
  .tmp-v<N>-<pid>-<hex6>/     build scratch; swept only when older than TMP_MAX_AGE_S

The row is canonical and the directory is a mirror: every write goes tmp dir -> self-check
(re-read + compile_stored == fields) -> rename into place under the lock. A crash between the
archive step and the final rename leaves no v<N>; the next call rebuilds from the row.

stdlib only. `config_hash` and `repo_root` are explicit parameters; nothing here reads the
process environment or imports config.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .compile import compile_stored, read_version_dir
from .decompose import NodeIntegrityError, decompose_row, node_to_frontmatter, sha256_text
from .diff import diff_versions, version_kind
from .edges import derive_edges, validate_graph, write_edges_json
from .frontmatter import atomic_write_text, write_node
from .lessons import DEFAULT_INJECTED_LIMIT
from .model import (
    AGENT_DIR, AGENT_PREFIX, Edge, FIELDS, GraphBuild, InheritedText, Node, RowMeta, VERSION_DIR_RE, Version,
    actor_kind, version_stamp,
)

MANIFEST_SCHEMA = 1
LOCK_TIMEOUT_S = 30.0          # bounded wait for the config-dir lock
LOCK_RETRY_S = 0.05            # LOCK_NB retry interval
TMP_MAX_AGE_S = 10 * 60        # .tmp-* dirs younger than this are never swept
GIT_TIMEOUT_S = 5
OVERLAY_OWNERS = {"code": "code", "ltm": "decider_memory"}   # overlay kind -> node owner
_GIT_FALLBACK = "worktree"


class StoreBusy(Exception):
    """The config-dir lock could not be acquired within LOCK_TIMEOUT_S."""


class RoundTripError(Exception):
    """The freshly written directory does not compile back to the row bytes (nothing landed)."""


@dataclass
class MaterializeResult:
    path: Path
    action: str            # created | unchanged | replaced | rebuilt
    roundtrip: str = "ok"


# ----------------------------------------------------------------------------- paths
def version_root(repo_root: Path, agent_type: str, config_hash: str) -> Path:
    if agent_type not in AGENT_DIR:
        raise ValueError(f"unknown agent_type {agent_type!r}")
    if not config_hash or "/" in str(config_hash) or str(config_hash).startswith("."):
        raise ValueError(f"bad config_hash {config_hash!r}")
    return Path(repo_root) / "agents" / AGENT_DIR[agent_type] / "policy-graph" / str(config_hash)


def version_dir(root: Path, version: int) -> Path:
    return Path(root) / f"v{int(version)}"


def list_version_dirs(root: Path) -> list:
    """Sorted version numbers that have a manifest.json under `root`."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for p in root.iterdir():
        m = VERSION_DIR_RE.match(p.name)
        if m and p.is_dir() and (p / "manifest.json").is_file():
            out.append(int(m.group(1)))
    return sorted(out)


# ----------------------------------------------------------------------------- small helpers
def _builder_version() -> int:
    from . import BUILDER_VERSION   # read at call time so a monkeypatched bump is honoured
    return int(BUILDER_VERSION)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def source_sha256(fields: dict) -> dict:
    """{field: sha256 hex | None} over the five columns (None for NULL)."""
    out = {}
    for f in FIELDS:
        v = (fields or {}).get(f)
        out[f] = None if v is None else sha256_text(v)
    return out


def _combined_sha8(shas: dict) -> str:
    payload = json.dumps([[f, shas.get(f)] for f in FIELDS], sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


def _read_manifest(path: Path) -> Optional[dict]:
    try:
        with open(Path(path) / "manifest.json", "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data) -> None:
    atomic_write_text(Path(path), json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_tree(path: Path) -> None:
    for p in Path(path).rglob("*"):
        if p.is_file():
            try:
                fd = os.open(str(p), os.O_RDONLY)
            except OSError:
                continue
            try:
                os.fsync(fd)
            except OSError:
                pass
            finally:
                os.close(fd)
    _fsync_dir(path)


def git_short_sha(repo_root: Path) -> str:
    """`git rev-parse --short HEAD` of the checkout, 'worktree' when git/the repo is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(repo_root), capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _GIT_FALLBACK
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and sha else _GIT_FALLBACK


# ----------------------------------------------------------------------------- lock
class _Lock:
    """fcntl.flock on <root>/.lock with a bounded LOCK_NB retry loop."""

    def __init__(self, root: Path, timeout: Optional[float] = None):
        self.path = Path(root) / ".lock"
        self.timeout = LOCK_TIMEOUT_S if timeout is None else timeout
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + max(0.0, float(self.timeout))
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
                return self
            except (BlockingIOError, InterruptedError, PermissionError):
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise StoreBusy(f"policy graph store busy: {self.path} held by another writer "
                                    f"for more than {self.timeout:.0f}s")
                time.sleep(LOCK_RETRY_S)

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None
        return False


def sweep_stale_tmp(root: Path, *, max_age_s: float = TMP_MAX_AGE_S, now: Optional[float] = None) -> list:
    """Remove `.tmp-*` build dirs older than max_age_s (a crashed writer); fresh ones are kept."""
    root = Path(root)
    now = time.time() if now is None else now
    removed = []
    if not root.is_dir():
        return removed
    for p in root.iterdir():
        if not p.name.startswith(".tmp-") or not p.is_dir():
            continue
        try:
            age = now - p.stat().st_mtime
        except OSError:
            continue
        if age > max_age_s:
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p)
    return removed


# ----------------------------------------------------------------------------- node file writing
def _write_nodes(dir_path: Path, nodes: list, stamp: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    for node in nodes:
        write_node(dir_path / f"{node.id}.md", node_to_frontmatter(node, stamp), node.body)


def _overlay_kind(node: Node) -> Optional[str]:
    for kind, owner in OVERLAY_OWNERS.items():
        if node.owner == owner:
            return kind
    return None


def write_overlay_dir(root: Path, kind: str, sha12: str, nodes: list, meta: dict) -> Path:
    """`<root>/_<kind>/<sha12>/` — content-addressed; written once via tmp+rename, never rewritten.

    Returns the overlay path (existing or new). `nodes` are written with a kind@sha stamp (they
    are shared by every version that links the same sha); `meta` becomes the overlay manifest."""
    if kind not in OVERLAY_OWNERS:
        raise ValueError(f"unknown overlay kind {kind!r}")
    if not sha12 or "/" in str(sha12):
        raise ValueError(f"bad overlay sha {sha12!r}")
    base = Path(root) / f"_{kind}"
    dest = base / str(sha12)
    if (dest / "manifest.json").is_file():
        return dest
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".tmp-{sha12}-{os.getpid()}-{secrets.token_hex(3)}"
    try:
        _write_nodes(tmp, nodes, f"{kind}@{sha12}")
        manifest = dict(meta or {})
        manifest.setdefault("kind", kind)
        manifest.setdefault("sha", str(sha12))
        manifest.setdefault("node_ids", [n.id for n in nodes])
        manifest.setdefault("written_at", _now_iso())
        _write_json(tmp / "manifest.json", manifest)
        _fsync_tree(tmp)
        try:
            os.rename(tmp, dest)
        except OSError:
            if (dest / "manifest.json").is_file():      # another writer won the race
                shutil.rmtree(tmp, ignore_errors=True)
                return dest
            raise
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _fsync_dir(base)
    return dest


def _complete_hierarchy(nodes: list, edges: list, stamp: str) -> list:
    """edges.json carries one subtype_of per non-root node; virtual ticker nodes are appended by
    derive_edges after its hierarchy pass, so their parent edge is added here."""
    have = {e.source for e in edges if e.edge_type == "subtype_of"}
    extra = [Edge(source=n.id, target=n.parent, edge_type="subtype_of", confidence=1.0,
                  provenance="derived:hierarchy", version=stamp)
             for n in nodes if n.parent and n.id not in have]
    if not extra:
        return edges
    return sorted(edges + extra, key=lambda e: (e.source, e.edge_type, e.target))


# ----------------------------------------------------------------------------- manifest
def _fields_equal(stored: dict, fields: dict) -> bool:
    for f in FIELDS:
        expected = (fields or {}).get(f)
        got = stored.get(f)
        if expected is None:
            if got is not None:
                return False
        elif got is None or got.encode("utf-8") != expected.encode("utf-8"):
            return False
    return True


def _unchanged(manifest: Optional[dict], shas: dict, code_sha: str, ltm_sha: str, fields_meta: dict) -> bool:
    if not manifest:
        return False
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("builder_version") != _builder_version():
        return False
    if manifest.get("source_sha256") != shas:
        return False
    if (manifest.get("code") or {}).get("sha") != code_sha:
        return False
    if (manifest.get("ltm") or {}).get("sha") != ltm_sha:
        return False
    old_fields = manifest.get("fields") or {}
    for f in FIELDS:
        if (old_fields.get(f) or {}).get("inherited_sha256") != (fields_meta.get(f) or {}).get("inherited_sha256"):
            return False
    return True


def _inherited_meta(inherited: dict) -> dict:
    """fields_meta-shaped view of the InheritedText inputs (for the unchanged check before decomposing)."""
    out = {}
    for f in FIELDS:
        inh = (inherited or {}).get(f)
        out[f] = {"inherited_sha256": sha256_text(inh.text) if isinstance(inh, InheritedText) and inh.text else None}
    return out


def _delta_and_kind(root: Path, version: int, cur: Version, history_count: int) -> tuple:
    """delta_vs_prev + kind against the previous version dir on disk (None/‘policy’ when absent)."""
    prev = None
    for v in reversed(list_version_dirs(root)):
        if v < int(version):
            try:
                prev = read_version_dir(version_dir(root, v))
            except Exception:
                prev = None
            break
    delta = None
    try:
        d = diff_versions(prev, cur)
        delta = {"added": len(d.added), "changed": len(d.changed), "removed": len(d.removed),
                 "renamed": len(d.renamed), "whitespace": len(d.whitespace_only),
                 "source_changed": list(d.source_changed),
                 "prev_version": prev.version if prev is not None else None}
        kind = version_kind(prev, cur, history_count)
    except Exception:   # the diff is informational; never block a write on it
        kind = "policy"
    return delta, kind


def build_manifest(*, agent_type: str, config_hash: str, version: int, build: GraphBuild, meta: RowMeta,
                   shas: dict, edges: list, node_count: int, code_sha: str, code_dir: Optional[str],
                   code_git_sha: str, code_fires: dict, ltm_sha: str, ltm_dir: Optional[str], ltm_snapshot: str,
                   ltm_row_ids: list, ltm_injected: list, materialized_by: str, lineage: Optional[dict],
                   history: list) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "builder_version": _builder_version(),
        "agent_type": agent_type,
        "prefix": AGENT_PREFIX[agent_type],
        "config_hash": str(config_hash),
        "version": int(version),
        "root_id": build.root_id,
        "prompt_version_id": meta.prompt_version_id,
        "created_at": _iso(meta.created_at),
        "created_by": meta.created_by,
        "actor_kind": actor_kind(meta.created_by),
        "description": meta.description or "",
        "is_active": bool(meta.is_active),
        "materialized_at": _now_iso(),
        "materialized_by": materialized_by,
        "pid": os.getpid(),
        "source_sha256": dict(shas),
        "fields": build.fields_meta,
        "compile_order": build.compile_order,
        "node_count": int(node_count),
        "edge_count": len(edges),
        "code": {"sha": code_sha, "dir": code_dir, "git_sha": code_git_sha, "fires": code_fires},
        "ltm": {"sha": ltm_sha, "dir": ltm_dir, "snapshot": ltm_snapshot, "injected_limit": DEFAULT_INJECTED_LIMIT,
                "row_ids": ltm_row_ids, "injected_ids": ltm_injected},
        "lineage": lineage,
        "delta_vs_prev": None,
        "kind": None,
        "history": list(history),
    }


# ----------------------------------------------------------------------------- materialize
def _finalize_rename(tmp: Path, dest: Path) -> None:
    """Step 8 (kept as a function so tests can inject a crash between steps 7 and 8)."""
    os.rename(tmp, dest)


def _archive_or_remove(root: Path, version: int, old_manifest: Optional[dict], shas: dict) -> tuple:
    """Step 7. Returns (action, history_entry|None)."""
    dest = version_dir(root, version)
    if not dest.exists():
        return "created", None
    old_shas = (old_manifest or {}).get("source_sha256")
    if old_manifest is not None and old_shas != shas:
        prior_root = root / "_prior"
        prior_root.mkdir(parents=True, exist_ok=True)
        base = f"v{int(version)}-{_combined_sha8(old_shas or {})}"
        prior = prior_root / base
        k = 2
        while prior.exists():
            prior = prior_root / f"{base}-{k}"
            k += 1
        os.rename(dest, prior)
        entry = {
            "source_sha256": old_shas,
            "materialized_at": old_manifest.get("materialized_at"),
            "materialized_by": old_manifest.get("materialized_by"),
            "prior_dir": f"../_prior/{prior.name}",
            "archived_at": _now_iso(),
        }
        return "replaced", entry
    shutil.rmtree(dest)
    return "rebuilt", None


def _adopt_pending(root: Path, version: int, fields: dict, shas: dict, materialized_by: str,
                   old_manifest: Optional[dict]) -> Optional[Path]:
    """Step 5: a Phase-2 staged dir whose compile equals the row bytes becomes v<N> as-is."""
    pending_root = root / "_pending"
    if not pending_root.is_dir():
        return None
    prefix = f"v{int(version)}-"
    for cand in sorted(pending_root.iterdir()):
        if not cand.is_dir() or not cand.name.startswith(prefix) or not (cand / "manifest.json").is_file():
            continue
        try:
            ver = read_version_dir(cand)
            if not _fields_equal(compile_stored(ver), fields):
                continue
        except Exception:
            continue
        action, entry = _archive_or_remove(root, version, old_manifest, shas)
        manifest = dict(ver.manifest)
        manifest["source_sha256"] = dict(shas)
        manifest["materialized_at"] = _now_iso()
        manifest["materialized_by"] = materialized_by
        manifest["pid"] = os.getpid()
        manifest["adopted_from"] = f"_pending/{cand.name}"
        if entry is not None:
            manifest["history"] = list(manifest.get("history") or []) + [entry]
        _write_json(cand / "manifest.json", manifest)
        _fsync_tree(cand)
        dest = version_dir(root, version)
        os.rename(cand, dest)
        _fsync_dir(root)
        return dest
    return None


def materialize(repo_root: Path, agent_type: str, config_hash: str, version: int, fields: dict, *,
                meta: RowMeta, inherited: dict, code_nodes: list, code_sha: str, ltm_nodes: list, ltm_sha: str,
                ltm_snapshot: str, is_margin_account: bool, materialized_by: str,
                lineage: Optional[dict] = None) -> MaterializeResult:
    """Mirror one prompt_versions row to disk (spec 5.3 steps 1-8). Idempotent: an up-to-date
    directory returns 'unchanged' without a single write."""
    root = version_root(repo_root, agent_type, config_hash)
    root.mkdir(parents=True, exist_ok=True)
    fields = {f: (fields or {}).get(f) for f in FIELDS}
    version = int(version)
    dest = version_dir(root, version)
    shas = source_sha256(fields)                                              # 1

    with _Lock(root):                                                         # 2
        sweep_stale_tmp(root)                                                 # 3
        old_manifest = _read_manifest(dest) if dest.is_dir() else None
        if _unchanged(old_manifest, shas, code_sha, ltm_sha, _inherited_meta(inherited)):   # 4
            return MaterializeResult(path=dest, action="unchanged", roundtrip="ok")

        adopted = _adopt_pending(root, version, fields, shas, materialized_by, old_manifest)   # 5
        if adopted is not None:
            return MaterializeResult(path=adopted, action="created", roundtrip="ok")

        # 6. decompose + write the scratch dir
        build = decompose_row(agent_type, config_hash, version, fields, meta=meta, inherited=inherited or {},
                              code_nodes=list(code_nodes or []), ltm_nodes=list(ltm_nodes or []),
                              is_margin_account=is_margin_account)
        stamp = version_stamp(agent_type, config_hash, version)
        edges = derive_edges(build.nodes, version_stamp=stamp)   # appends virtual ticker nodes in place
        edges = _complete_hierarchy(build.nodes, edges, stamp)
        problems = validate_graph(build.nodes, edges, root_id=build.root_id)
        if problems:
            raise RoundTripError(f"{agent_type} v{version}: graph invalid: " + "; ".join(problems[:5]))

        overlay_nodes = {"code": [], "ltm": []}
        in_place = []
        for n in build.nodes:
            kind = _overlay_kind(n)
            if kind is None:
                in_place.append(n)
            else:
                overlay_nodes[kind].append(n)

        code_git_sha = git_short_sha(repo_root)
        code_dir = ltm_dir = None
        if overlay_nodes["code"]:
            p = write_overlay_dir(root, "code", code_sha, overlay_nodes["code"],
                                  {"code_sha": code_sha, "git_sha": code_git_sha, "extracted_at": _now_iso()})
            code_dir = f"../_code/{p.name}"
        if overlay_nodes["ltm"]:
            p = write_overlay_dir(root, "ltm", ltm_sha, overlay_nodes["ltm"],
                                  {"ltm_sha": ltm_sha, "snapshot": ltm_snapshot, "extracted_at": _now_iso()})
            ltm_dir = f"../_ltm/{p.name}"
        code_fires = {n.id: bool(n.extra.get("fires")) for n in overlay_nodes["code"] if n.node_type == "code"}
        ltm_rows = [n for n in overlay_nodes["ltm"] if n.node_type == "ltm" and n.id.count(".") == 2]
        ltm_row_ids, ltm_injected = [], []
        for n in ltm_rows:
            try:
                rid = int(n.id.rsplit(".", 1)[-1])
            except ValueError:
                continue
            ltm_row_ids.append(rid)
            if n.extra.get("injected"):
                ltm_injected.append(rid)

        # an archive entry is appended only once the rename in step 7 has actually happened
        history = list((old_manifest or {}).get("history") or [])

        tmp = root / f".tmp-v{version}-{os.getpid()}-{secrets.token_hex(3)}"
        try:
            _write_nodes(tmp, in_place, stamp)
            write_edges_json(tmp / "edges.json", edges)
            manifest = build_manifest(
                agent_type=agent_type, config_hash=config_hash, version=version, build=build, meta=meta, shas=shas,
                edges=edges, node_count=len(build.nodes), code_sha=code_sha, code_dir=code_dir,
                code_git_sha=code_git_sha, code_fires=code_fires, ltm_sha=ltm_sha, ltm_dir=ltm_dir,
                ltm_snapshot=ltm_snapshot, ltm_row_ids=ltm_row_ids, ltm_injected=ltm_injected,
                materialized_by=materialized_by, lineage=lineage, history=history,
            )
            cur_mem = Version(path=tmp, manifest=manifest, nodes={n.id: n for n in build.nodes}, edges=edges)
            delta, kind = _delta_and_kind(root, version, cur_mem, len(history))
            manifest["delta_vs_prev"] = delta
            manifest["kind"] = kind
            _write_json(tmp / "manifest.json", manifest)
            _fsync_tree(tmp)

            # self-check: re-read and compile
            try:
                reread = read_version_dir(tmp)
                stored = compile_stored(reread)
            except NodeIntegrityError as exc:
                raise RoundTripError(f"{agent_type} v{version}: {exc}") from exc
            if not _fields_equal(stored, fields):
                bad = [f for f in FIELDS if (stored.get(f) or "") != (fields.get(f) or "")
                       or (stored.get(f) is None) != (fields.get(f) is None)]
                raise RoundTripError(f"{agent_type} v{version}: compile_stored != row for {bad}")
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        # 7. archive (row bytes changed) or remove (overlay/builder rebuild) the existing dir
        action, entry = _archive_or_remove(root, version, old_manifest, shas)
        if entry is not None:
            manifest["history"] = history + [entry]
            _write_json(tmp / "manifest.json", manifest)
            _fsync_tree(tmp)
        # 8. into place
        _finalize_rename(tmp, dest)
        _fsync_dir(root)
        return MaterializeResult(path=dest, action=action, roundtrip="ok")


__all__ = [
    "StoreBusy", "RoundTripError", "MaterializeResult", "version_root", "version_dir", "list_version_dirs",
    "materialize", "write_overlay_dir", "sweep_stale_tmp", "source_sha256", "git_short_sha", "build_manifest",
    "LOCK_TIMEOUT_S", "TMP_MAX_AGE_S", "MANIFEST_SCHEMA",
]
