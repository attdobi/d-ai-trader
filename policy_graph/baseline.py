"""The committed baseline graph: `agents/<dir>/policy-graph/baseline/v0/`.

A fresh checkout has no database history, so the repository carries the v0 policy of every
agent as guideline files — the same decomposition `init_database` produces for a new config's
v0 rows, written under the pseudo config hash `baseline` from `initialize_prompts.DEFAULT_PROMPTS`
(system/user templates, strategy directives, and the committed SOUL.default.md / MEMORY.default.md).
Personal evolution (v1…) lives under the machine's own config hash and is not needed to start.

    ./dai/bin/python -m policy_graph.backfill --baseline        # regenerate after editing the defaults
    tests/test_policy_graph_baseline.py                          # fails when the committed files drift

Volatile manifest keys (timestamps, pid, git sha) are scrubbed so regeneration is byte-stable.
`initialize_prompts` is imported lazily inside `baseline_fields` (it reads only agents/*.md files).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import code_blocks, store
from .model import AGENT_DIR, AGENT_PREFIX, FIELDS, RowMeta

BASELINE_HASH = "baseline"
BASELINE_CREATED_AT = datetime(2026, 1, 1, 0, 0, 0)
_VOLATILE = ("materialized_at", "pid", "written_at", "extracted_at")


def baseline_fields(agent_type: str) -> dict:
    """The five prompt fields of an agent's v0 exactly as init_database seeds them."""
    from initialize_prompts import DEFAULT_PROMPTS   # lazy: outside the package's import rules
    payload = DEFAULT_PROMPTS[agent_type]
    return {
        "system_prompt": (payload.get("system_prompt") or "").strip(),
        "user_prompt_template": (payload.get("user_prompt_template") or payload.get("user_prompt") or "").strip(),
        "strategy_directives": (payload.get("strategy_directives") or "").strip(),
        "soul": (payload.get("soul") or "").strip(),
        "memory": (payload.get("memory") or "").strip(),
    }


def baseline_root(repo_root: Path, agent_type: str) -> Path:
    return store.version_root(Path(repo_root), agent_type, BASELINE_HASH)


def _scrub(path: Path) -> None:
    """Remove volatile keys from every manifest under `path` so the tree is reproducible."""
    store.scrub_volatile(path)
    for m in Path(path).rglob("manifest.json"):
        data = json.loads(m.read_text(encoding="utf-8"))
        changed = False
        code = data.get("code")
        if isinstance(code, dict) and code.get("git_sha") not in (None, BASELINE_HASH):
            code["git_sha"] = BASELINE_HASH
            changed = True
        if data.get("git_sha") not in (None, BASELINE_HASH) and "git_sha" in data:
            data["git_sha"] = BASELINE_HASH
            changed = True
        if changed:
            m.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def write_baseline(repo_root: Path, *, agents=None, is_margin_account: bool = False, force: bool = True) -> list:
    """Materialize v0 of every agent under the baseline hash. Returns [(agent, action, path)]."""
    repo_root = Path(repo_root)
    out = []
    for agent_type in (agents or list(AGENT_PREFIX)):
        fields = baseline_fields(agent_type)
        root = baseline_root(repo_root, agent_type)
        if force and (root / "v0").is_dir():
            import shutil
            shutil.rmtree(root / "v0")
        meta = RowMeta(prompt_version_id=0, created_at=BASELINE_CREATED_AT, created_by="init_database",
                       description=f"v0 baseline {agent_type} — committed with the repository", is_active=True)
        cnodes = code_blocks.code_nodes(agent_type, fields, is_margin_account=is_margin_account)
        res = store.materialize(repo_root, agent_type, BASELINE_HASH, 0, fields, meta=meta, inherited={},
                                code_nodes=cnodes, code_sha=code_blocks.CODE_SHA, ltm_nodes=[],
                                ltm_sha=_empty_ltm_sha(), ltm_snapshot="none", is_margin_account=is_margin_account,
                                materialized_by="baseline", lineage=None)
        _scrub(root)
        lock = root / ".lock"
        if lock.exists():
            lock.unlink()
        out.append((agent_type, res.action, res.path))
    return out


def _empty_ltm_sha() -> str:
    from . import lessons
    return lessons.snapshot_sha([])


def verify_baseline(repo_root: Path, *, agents=None) -> list:
    """[(agent, problem)] — empty when every committed v0 compiles to today's DEFAULT_PROMPTS."""
    from .compile import compile_stored, read_version_dir
    problems = []
    for agent_type in (agents or list(AGENT_PREFIX)):
        path = baseline_root(repo_root, agent_type) / "v0"
        if not (path / "manifest.json").is_file():
            problems.append((agent_type, f"missing {path}"))
            continue
        try:
            version = read_version_dir(path)
            stored = compile_stored(version)
        except Exception as exc:     # noqa: BLE001
            problems.append((agent_type, f"unreadable: {exc}"))
            continue
        want = baseline_fields(agent_type)
        for f in FIELDS:
            a, b = stored.get(f), want.get(f)
            if (a or "") != (b or ""):
                problems.append((agent_type, f"{f} differs from initialize_prompts.DEFAULT_PROMPTS"))
    return problems


__all__ = ["BASELINE_HASH", "baseline_fields", "baseline_root", "write_baseline", "verify_baseline"]
