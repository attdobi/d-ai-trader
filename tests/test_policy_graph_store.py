"""policy_graph.store — the on-disk mirror of prompt_versions rows (spec section 5, tests item 4).

DB-free: rows come from tests/fixtures/policy_graph, everything is written under tmp_path.
"""
from __future__ import annotations

import fcntl
import importlib
import io
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import tokenize
import types
from datetime import datetime
from pathlib import Path

import pytest

import policy_graph
from policy_graph import store
from policy_graph.code_blocks import CODE_SHA, code_nodes
from policy_graph.compile import compile_stored, read_version_dir
from policy_graph.decompose import NodeIntegrityError
from policy_graph.edges import validate_graph
from policy_graph.lessons import ltm_nodes
from policy_graph.model import AGENT_DIR, FIELDS, InheritedText, RowMeta

REPO = Path(__file__).resolve().parent.parent
FX = REPO / "tests" / "fixtures" / "policy_graph"
INDEX = json.loads((FX / "INDEX.json").read_text(encoding="utf-8"))
CFG = "cfg_test"
AGENT = "DeciderAgent"

LTM_ROWS = [
    {"id": 1, "content": "Never chase a gap above 5% at the open", "active": True, "weight": 2.0,
     "tags": ["gap-chase"], "ticker": "IRDM", "kind": "rule", "source": "human",
     "created_at": "2026-08-01T00:00:00", "updated_at": "2026-08-01T00:00:00"},
    {"id": 2, "content": "Regime gate beats momentum in a down tape", "active": False, "weight": 1.0,
     "tags": None, "ticker": None, "kind": "lesson", "source": "feedback",
     "created_at": "2026-08-02T00:00:00", "updated_at": "2026-08-02T00:00:00"},
]


# ----------------------------------------------------------------------------- helpers
def fixture_fields(agent: str, version: int) -> tuple:
    fields, entry = {f: None for f in FIELDS}, None
    for e in INDEX:
        if e["agent_type"] == agent and e["version"] == version:
            fields[e["field"]] = (FX / e["file"]).read_bytes().decode("utf-8")
            entry = e
    assert entry is not None, f"no fixture for {agent} v{version}"
    return fields, entry


def meta_for(entry: dict, **kw) -> RowMeta:
    return RowMeta(
        prompt_version_id=entry.get("prompt_version_id", 1),
        created_at=datetime.fromisoformat(entry["created_at"]) if entry.get("created_at") else datetime(2026, 9, 2),
        created_by=entry.get("created_by", "prompt_lab"),
        description=entry.get("description", ""),
        is_active=kw.get("is_active", False),
    )


def materialize(repo_root: Path, version: int, fields: dict, *, entry: dict | None = None, agent: str = AGENT,
                inherited: dict | None = None, ltm_rows: list | None = None, config_hash: str = CFG, **kw):
    entry = entry or {"prompt_version_id": 100 + version, "created_at": "2026-09-02 14:57:20", "created_by": "prompt_lab",
                      "description": f"test v{version}"}
    cn = code_nodes(agent, fields, is_margin_account=False)
    if agent == AGENT:
        ltm_sha, ln = ltm_nodes(ltm_rows if ltm_rows is not None else LTM_ROWS)
    else:
        ltm_sha, ln = "none", []
    kwargs = dict(meta=meta_for(entry), inherited=inherited or {}, code_nodes=cn, code_sha=CODE_SHA, ltm_nodes=ln,
                  ltm_sha=ltm_sha, ltm_snapshot="live", is_margin_account=False, materialized_by="test")
    kwargs.update(kw)
    return store.materialize(repo_root, agent, config_hash, version, fields, **kwargs)


def v21_fields() -> dict:
    return fixture_fields(AGENT, 21)[0]


def tmp_dirs(root: Path) -> list:
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".tmp-"))


# ----------------------------------------------------------------------------- layout
def test_version_root_uses_explicit_repo_root_and_config_hash(tmp_path):
    root = store.version_root(tmp_path, AGENT, CFG)
    assert root == tmp_path / "agents" / "decider" / "policy-graph" / CFG
    assert store.version_root(tmp_path, "SummarizerAgent", "9ea09b9as") == tmp_path / "agents" / "summarizer" / "policy-graph" / "9ea09b9as"
    with pytest.raises(ValueError):
        store.version_root(tmp_path, "NoSuchAgent", CFG)
    with pytest.raises(ValueError):
        store.version_root(tmp_path, AGENT, "../escape")


def test_explicit_config_hash_path_and_list_version_dirs(tmp_path):
    fields = v21_fields()
    res = materialize(tmp_path, 1, fields, config_hash="cfg_test")
    assert res.action == "created" and res.roundtrip == "ok"
    assert res.path == tmp_path / "agents" / "decider" / "policy-graph" / "cfg_test" / "v1"
    root = res.path.parent
    (root / "v7").mkdir()                       # no manifest → not listed
    (root / "vx").mkdir()
    materialize(tmp_path, 3, fields)
    assert store.list_version_dirs(root) == [1, 3]
    assert store.list_version_dirs(tmp_path / "nowhere") == []


# ----------------------------------------------------------------------------- created / unchanged / replaced / rebuilt
def test_created_then_unchanged_then_replaced_with_prior_and_history(tmp_path):
    fields = v21_fields()
    res = materialize(tmp_path, 1, fields)
    assert res.action == "created"
    vdir = res.path
    root = vdir.parent
    manifest = json.loads((vdir / "manifest.json").read_text(encoding="utf-8"))
    ver = read_version_dir(vdir)
    assert compile_stored(ver) == fields                      # byte-exact mirror
    assert validate_graph(list(ver.nodes.values()), ver.edges, root_id=manifest["root_id"]) == []
    assert manifest["history"] == [] and manifest["schema"] == 1
    assert manifest["builder_version"] == policy_graph.BUILDER_VERSION
    assert manifest["source_sha256"] == store.source_sha256(fields)
    assert manifest["node_count"] == len(ver.nodes) and manifest["edge_count"] == len(ver.edges)
    assert set((vdir / "edges.json").read_text().splitlines()[:1]) == {"["}

    before_dir = vdir.stat().st_mtime_ns
    before_manifest = (vdir / "manifest.json").stat().st_mtime_ns
    before_node = (vdir / "DA.directives.md").stat().st_mtime_ns
    time.sleep(0.02)
    res2 = materialize(tmp_path, 1, fields)
    assert res2.action == "unchanged"
    assert vdir.stat().st_mtime_ns == before_dir
    assert (vdir / "manifest.json").stat().st_mtime_ns == before_manifest
    assert (vdir / "DA.directives.md").stat().st_mtime_ns == before_node
    assert tmp_dirs(root) == []

    changed = dict(fields)
    changed["memory"] = fields["memory"] + "\n\n## 2026-09-03 #IRDM #weekly-append\n- appended by the weekly path"
    res3 = materialize(tmp_path, 1, changed)
    assert res3.action == "replaced"
    assert compile_stored(read_version_dir(vdir)) == changed
    priors = sorted((root / "_prior").iterdir())
    assert len(priors) == 1
    old_sha8 = store._combined_sha8(store.source_sha256(fields))
    assert priors[0].name == f"v1-{old_sha8}"
    assert compile_stored(read_version_dir(priors[0])) == fields     # the archive is the old mirror, intact
    m3 = json.loads((vdir / "manifest.json").read_text(encoding="utf-8"))
    assert len(m3["history"]) == 1
    assert m3["history"][0]["prior_dir"] == f"../_prior/v1-{old_sha8}"
    assert m3["history"][0]["source_sha256"] == store.source_sha256(fields)
    assert "DA.memory.log.2026_09_03_irdm" in read_version_dir(vdir).nodes
    assert tmp_dirs(root) == []


def test_builder_version_bump_rebuilds_without_prior(tmp_path, monkeypatch):
    fields = v21_fields()
    res = materialize(tmp_path, 2, fields)
    assert res.action == "created"
    root = res.path.parent
    monkeypatch.setattr(policy_graph, "BUILDER_VERSION", policy_graph.BUILDER_VERSION + 1)
    res2 = materialize(tmp_path, 2, fields)
    assert res2.action == "rebuilt"
    assert not (root / "_prior").exists()
    m = json.loads((res2.path / "manifest.json").read_text(encoding="utf-8"))
    assert m["builder_version"] == policy_graph.BUILDER_VERSION and m["history"] == []
    assert materialize(tmp_path, 2, fields).action == "unchanged"


def test_overlay_change_rebuilds_in_place_without_prior(tmp_path):
    fields = v21_fields()
    res = materialize(tmp_path, 1, fields)
    root = res.path.parent
    m1 = json.loads((res.path / "manifest.json").read_text(encoding="utf-8"))
    rows = LTM_ROWS + [{"id": 3, "content": "New lesson row", "active": True, "weight": 1.5, "tags": ["regime"],
                        "ticker": "SPY", "kind": "rule", "source": "feedback",
                        "created_at": "2026-09-01T00:00:00", "updated_at": "2026-09-01T00:00:00"}]
    res2 = materialize(tmp_path, 1, fields, ltm_rows=rows)
    assert res2.action == "rebuilt"
    assert not (root / "_prior").exists()
    m2 = json.loads((res2.path / "manifest.json").read_text(encoding="utf-8"))
    assert m2["ltm"]["sha"] != m1["ltm"]["sha"]
    assert m2["ltm"]["row_ids"] == [1, 3, 2] and m2["ltm"]["injected_ids"] == [1, 3]
    assert sorted(p.name for p in (root / "_ltm").iterdir()) == sorted({m1["ltm"]["sha"], m2["ltm"]["sha"]})
    ver = read_version_dir(res2.path)
    assert "DA.ltm.3" in ver.nodes and ver.nodes["DA.ltm.3"].parent == "DA.ltm"


def test_inherited_default_change_rebuilds(tmp_path):
    fields = v21_fields()
    fields["soul"] = ""
    inh = InheritedText(text="# Decider Agent — Soul\n\n## Mission\nFirst default.", source_path="agents/decider/SOUL.default.md",
                        git_sha="2849237f", resolution="git-blob-at-created_at")
    res = materialize(tmp_path, 4, fields, inherited={"soul": inh})
    assert res.action == "created"
    m = json.loads((res.path / "manifest.json").read_text(encoding="utf-8"))
    assert m["fields"]["soul"]["inherited"] is True
    assert m["fields"]["soul"]["inherited_git_sha"] == "2849237f"
    assert m["compile_order"]["soul"] == []
    ver = read_version_dir(res.path)
    assert compile_stored(ver)["soul"] == ""
    assert ver.nodes["DA.soul"].owner == "default-file"
    assert materialize(tmp_path, 4, fields, inherited={"soul": inh}).action == "unchanged"
    inh2 = InheritedText(text=inh.text + "\nSecond default.", source_path=inh.source_path, git_sha="54a50e5e",
                         resolution="git-blob-at-created_at")
    res3 = materialize(tmp_path, 4, fields, inherited={"soul": inh2})
    assert res3.action == "rebuilt"
    assert not (res.path.parent / "_prior").exists()


# ----------------------------------------------------------------------------- manifest shape
def test_manifest_schema_fields(tmp_path):
    fields, entry = fixture_fields(AGENT, 21)
    lineage = {"parent_version": 20, "lineage_version": 21, "activation": None, "review": None}
    res = materialize(tmp_path, 21, fields, entry=entry, lineage=lineage)
    m = json.loads((res.path / "manifest.json").read_text(encoding="utf-8"))
    for key in ("schema", "builder_version", "agent_type", "prefix", "config_hash", "version", "root_id",
                "prompt_version_id", "created_at", "created_by", "actor_kind", "description", "materialized_at",
                "materialized_by", "pid", "source_sha256", "fields", "compile_order", "node_count", "edge_count",
                "code", "ltm", "lineage", "delta_vs_prev", "history"):
        assert key in m, key
    assert m["agent_type"] == AGENT and m["prefix"] == "DA" and m["config_hash"] == CFG and m["version"] == 21
    assert m["root_id"] == "DA.root" and m["prompt_version_id"] == 599 and m["created_by"] == "claude_code"
    assert m["actor_kind"] == "claude_code" and m["created_at"] == "2026-09-02T14:57:20.858624"
    assert m["materialized_by"] == "test" and m["pid"] == os.getpid()
    assert m["lineage"] == lineage
    assert set(m["source_sha256"]) == set(FIELDS)
    assert set(m["compile_order"]) == set(FIELDS)
    assert m["compile_order"]["system_prompt"] == ["DA.template.system"]
    assert m["compile_order"]["strategy_directives"][:3] == ["DA.directives", "DA.directives.ground_truth", "DA.directives.strategy"]
    assert m["fields"]["soul"] == {"stored_null": False, "stored_empty": False, "inherited": False}
    assert m["code"]["sha"] == CODE_SHA and m["code"]["dir"] == f"../_code/{CODE_SHA}"
    assert m["code"]["fires"]["DA.code.crowd_fade"] is True and m["code"]["fires"]["DA.code.json_fallback"] is False
    assert m["code"]["git_sha"]
    assert m["ltm"]["dir"].startswith("../_ltm/") and m["ltm"]["snapshot"] == "live"
    assert m["ltm"]["row_ids"] == [1, 2] and m["ltm"]["injected_limit"] == 14
    assert m["delta_vs_prev"]["prev_version"] is None       # no older dir on disk
    assert m["kind"] == "rewrite"
    # overlays: code nodes live in _code/<sha12>, ltm rows in _ltm/<sha12>, everything else in place
    root = res.path.parent
    assert (root / "_code" / CODE_SHA / "DA.code.crowd_fade.md").is_file()
    assert (root / "_code" / CODE_SHA / "manifest.json").is_file()
    assert not (res.path / "DA.code.crowd_fade.md").exists()
    assert (res.path / "DA.code.md").is_file()
    ltm_dir = (res.path / m["ltm"]["dir"]).resolve()
    assert (ltm_dir / "DA.ltm.md").is_file() and (ltm_dir / "DA.ltm.1.md").is_file()
    assert not (res.path / "DA.ltm.1.md").exists()
    # every node file in the version dir is named after its id and the reader merges the overlays
    ver = read_version_dir(res.path)
    for p in res.path.glob("*.md"):
        assert p.stem in ver.nodes
    assert "DA.code.crowd_fade" in ver.nodes and "DA.ltm.1" in ver.nodes


def test_edges_json_sorted_with_trailing_newline(tmp_path):
    res = materialize(tmp_path, 1, v21_fields())
    raw = (res.path / "edges.json").read_bytes()
    assert raw.endswith(b"]\n")
    records = json.loads(raw)
    keys = [(r["source_node_id"], r["edge_type"], r["target_node_id"]) for r in records]
    assert keys == sorted(keys)
    non_root = [p.stem for p in res.path.glob("*.md") if p.stem != "DA.root"]
    subtype_sources = {r["source_node_id"] for r in records if r["edge_type"] == "subtype_of"}
    assert set(non_root) <= subtype_sources


def test_non_decider_agent_has_no_ltm_overlay(tmp_path):
    fields, entry = fixture_fields("FeedbackAgent", 8)
    res = materialize(tmp_path, 8, fields, entry=entry, agent="FeedbackAgent")
    assert res.path == tmp_path / "agents" / "feedback" / "policy-graph" / CFG / "v8"
    m = json.loads((res.path / "manifest.json").read_text(encoding="utf-8"))
    assert m["ltm"]["dir"] is None and m["ltm"]["row_ids"] == []
    assert not (res.path.parent / "_ltm").exists()
    assert (res.path.parent / "_code" / CODE_SHA / "FA.code.system_base.md").is_file()
    assert compile_stored(read_version_dir(res.path)) == fields


# ----------------------------------------------------------------------------- overlays are content-addressed
def test_write_overlay_dir_never_rewritten(tmp_path):
    root = tmp_path / "root"
    cn = code_nodes(AGENT, v21_fields(), is_margin_account=False)
    p = store.write_overlay_dir(root, "code", "abc123abc123", cn, {"code_sha": "abc123abc123", "git_sha": "x"})
    assert p == root / "_code" / "abc123abc123"
    marker = p / "DA.code.crowd_fade.md"
    stamp = marker.stat().st_mtime_ns
    manifest = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["code_sha"] == "abc123abc123" and manifest["kind"] == "code"
    time.sleep(0.01)
    p2 = store.write_overlay_dir(root, "code", "abc123abc123", [], {"code_sha": "other"})
    assert p2 == p and marker.stat().st_mtime_ns == stamp
    assert json.loads((p / "manifest.json").read_text(encoding="utf-8"))["code_sha"] == "abc123abc123"
    assert not [q for q in (root / "_code").iterdir() if q.name.startswith(".tmp-")]
    with pytest.raises(ValueError):
        store.write_overlay_dir(root, "proposals", "abc", [], {})


# ----------------------------------------------------------------------------- concurrency, crashes, locks
def _worker(repo_root: str, version: int, q) -> None:
    fields = v21_fields()
    try:
        res = materialize(Path(repo_root), version, fields)
        q.put(res.action)
    except Exception as exc:   # pragma: no cover - reported to the parent
        q.put(f"error: {exc!r}")


def test_two_workers_same_version_one_valid_dir_no_tmp_leftovers(tmp_path):
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(str(tmp_path), 5, q)) for _ in range(2)]
    for p in procs:
        p.start()
    results = [q.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs)
    assert sorted(results) == ["created", "unchanged"], results
    root = store.version_root(tmp_path, AGENT, CFG)
    assert store.list_version_dirs(root) == [5]
    assert tmp_dirs(root) == []
    assert not (root / "_prior").exists()
    ver = read_version_dir(root / "v5")
    assert compile_stored(ver) == v21_fields()
    assert validate_graph(list(ver.nodes.values()), ver.edges, root_id="DA.root") == []


def test_crash_between_archive_and_rename_rebuilds_on_next_call(tmp_path, monkeypatch):
    fields = v21_fields()
    res = materialize(tmp_path, 1, fields)
    root = res.path.parent
    changed = dict(fields)
    changed["strategy_directives"] = fields["strategy_directives"] + "\n\nLatest Feedback Reminder: crash test."

    def boom(tmp, dest):
        raise RuntimeError("simulated crash after step 7")

    monkeypatch.setattr(store, "_finalize_rename", boom)
    with pytest.raises(RuntimeError):
        materialize(tmp_path, 1, changed)
    assert not (root / "v1").exists()                       # step 7 archived it; step 8 never ran
    assert len(list((root / "_prior").iterdir())) == 1
    monkeypatch.undo()
    res2 = materialize(tmp_path, 1, changed)
    assert res2.action == "created"
    assert compile_stored(read_version_dir(root / "v1")) == changed
    assert tmp_dirs(root) == [] or all(root.joinpath(d).is_dir() for d in tmp_dirs(root))   # leftover scratch is swept by age


def test_lock_timeout_raises_store_busy_and_never_proceeds(tmp_path, monkeypatch):
    fields = v21_fields()
    root = store.version_root(tmp_path, AGENT, CFG)
    root.mkdir(parents=True)
    fd = os.open(str(root / ".lock"), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    monkeypatch.setattr(store, "LOCK_TIMEOUT_S", 0.3)
    try:
        t0 = time.monotonic()
        with pytest.raises(store.StoreBusy):
            materialize(tmp_path, 1, fields)
        assert 0.25 <= time.monotonic() - t0 < 5
        assert not (root / "v1").exists() and tmp_dirs(root) == []
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert materialize(tmp_path, 1, fields).action == "created"


def test_stale_tmp_swept_fresh_kept(tmp_path):
    root = store.version_root(tmp_path, AGENT, CFG)
    root.mkdir(parents=True)
    stale = root / ".tmp-v1-999-abcdef"
    stale.mkdir()
    (stale / "DA.root.md").write_text("junk")
    old = time.time() - 11 * 60
    os.utime(stale, (old, old))
    fresh = root / ".tmp-v1-998-123456"
    fresh.mkdir()
    unrelated = root / "notes.txt"
    unrelated.write_text("keep")
    materialize(tmp_path, 1, v21_fields())
    assert not stale.exists()
    assert fresh.is_dir() and unrelated.is_file()
    assert (root / "v1").is_dir()


# ----------------------------------------------------------------------------- round-trip guard
def test_roundtrip_mismatch_raises_and_leaves_nothing(tmp_path, monkeypatch):
    real = store.compile_stored

    def corrupt(version):
        out = real(version)
        out["memory"] = (out["memory"] or "") + "X"
        return out

    monkeypatch.setattr(store, "compile_stored", corrupt)
    root = store.version_root(tmp_path, AGENT, CFG)
    with pytest.raises(store.RoundTripError):
        materialize(tmp_path, 1, v21_fields())
    assert not (root / "v1").exists() and tmp_dirs(root) == []


def test_node_integrity_error_is_wrapped_as_roundtrip_error(tmp_path, monkeypatch):
    def broken(path):
        raise NodeIntegrityError("DA.root: body_sha256 mismatch")

    monkeypatch.setattr(store, "read_version_dir", broken)
    root = store.version_root(tmp_path, AGENT, CFG)
    with pytest.raises(store.RoundTripError):
        materialize(tmp_path, 1, v21_fields())
    assert not (root / "v1").exists() and tmp_dirs(root) == []


# ----------------------------------------------------------------------------- _pending adoption
def test_pending_dir_with_matching_compile_is_adopted(tmp_path):
    fields = v21_fields()
    res = materialize(tmp_path, 9, fields)
    root = res.path.parent
    pending = root / "_pending" / "v9-proposal_42"
    pending.parent.mkdir()
    shutil.move(str(res.path), str(pending))
    m = json.loads((pending / "manifest.json").read_text(encoding="utf-8"))
    m["description"] = "AUTHORED IN PHASE 2"
    (pending / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    res2 = materialize(tmp_path, 9, fields)
    assert res2.action == "created" and res2.path == root / "v9"
    assert not pending.exists()
    m2 = json.loads((root / "v9" / "manifest.json").read_text(encoding="utf-8"))
    assert m2["description"] == "AUTHORED IN PHASE 2"            # adopted, not re-decomposed
    assert m2["adopted_from"] == "_pending/v9-proposal_42"
    assert compile_stored(read_version_dir(root / "v9")) == fields


def test_pending_dir_with_different_bytes_is_ignored(tmp_path):
    fields = v21_fields()
    res = materialize(tmp_path, 9, fields)
    root = res.path.parent
    pending = root / "_pending" / "v9-proposal_43"
    pending.parent.mkdir()
    shutil.move(str(res.path), str(pending))
    other = dict(fields)
    other["soul"] = fields["soul"] + "\n\nExtra paragraph."
    res2 = materialize(tmp_path, 9, other)
    assert res2.action == "created"
    assert pending.exists()                                      # left for Phase 2 to resolve
    assert compile_stored(read_version_dir(root / "v9")) == other


# ----------------------------------------------------------------------------- import hygiene
def _code_text(path: Path) -> str:
    """Source with COMMENT and STRING tokens removed (docstrings may mention the forbidden names)."""
    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


def test_package_never_reads_environment_or_config_hash_globals():
    pkg = REPO / "policy_graph"
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        code = _code_text(path)
        needles = ["environ", "getenv", "get_current_config_hash"]
        if path.name != "backfill.py":          # spec section 1: backfill imports config lazily inside main()
            needles += ["import config", "from config"]
        for needle in needles:
            if needle in code:
                offenders.append((path.name, needle))
    assert offenders == []


def test_subprocess_import_does_not_pull_config():
    script = (
        "import sys, importlib, pkgutil; import policy_graph; "
        "[importlib.import_module('policy_graph.' + m.name) for m in pkgutil.iter_modules(policy_graph.__path__) "
        " if m.name != 'routes']; "   # routes needs flask; every other module (backfill included) must stay config-free
        "assert 'config' not in sys.modules, sorted(m for m in sys.modules if m.startswith('config')); print('ok')"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_agent_dir_matches_prompt_manager_map(monkeypatch):
    config_stub = types.ModuleType("config")
    config_stub.engine = None
    config_stub.get_current_config_hash = lambda: CFG
    monkeypatch.setitem(sys.modules, "config", config_stub)
    monkeypatch.delitem(sys.modules, "prompt_manager", raising=False)
    pm = importlib.import_module("prompt_manager")
    try:
        expected = {k: v for k, v in pm._AGENT_DIR_MAP.items() if k != "feedback_analyzer"}
        assert AGENT_DIR == expected
    finally:
        sys.modules.pop("prompt_manager", None)


def test_store_and_diff_exports():
    for name in ("StoreBusy", "RoundTripError", "version_root", "list_version_dirs", "materialize", "write_overlay_dir"):
        assert hasattr(store, name)
    assert issubclass(store.StoreBusy, Exception) and issubclass(store.RoundTripError, Exception)
    buf = io.StringIO()
    print(store.MaterializeResult(path=Path("x"), action="created"), file=buf)
    assert "created" in buf.getvalue()
