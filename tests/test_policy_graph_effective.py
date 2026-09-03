"""Inherited defaults: git-blob-at-created_at resolution on a temp git repo, worktree / live-mirror
fallbacks, and (when the Core track's compile.py/decompose.py are present) the compile_effective
substitution for an empty stored soul."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from policy_graph.inherited import (
    _before_stamp, default_filename, git_text_at, resolve_inherited, worktree_text,
)
from policy_graph.model import InheritedText

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "policy_graph"
GIT = shutil.which("git")

V1_TEXT = "# Decider Agent — Soul\n\n## Mission\nFirst committed default.\n"
V2_TEXT = "# Decider Agent — Soul\n\n## Mission\nSecond committed default (rewritten).\n"
WORKTREE_TEXT = "# Decider Agent — Soul\n\n## Mission\nUncommitted worktree edit.\n\n"


def _git(repo: Path, *args, date: str | None = None):
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1"})
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", *args], cwd=str(repo), env=env, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    """Temp git repo: agents/decider/SOUL.default.md committed twice (May 29, Jun 29 -0700), then edited."""
    if not GIT:
        pytest.skip("git binary not available")
    root = tmp_path / "repo"
    (root / "agents" / "decider").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root", date="2026-05-01T09:00:00-07:00")
    path = root / "agents" / "decider" / "SOUL.default.md"
    path.write_text(V1_TEXT, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed soul", date="2026-05-29T09:49:28-07:00")
    sha1 = _git(root, "rev-parse", "--short", "HEAD").strip()
    path.write_text(V2_TEXT, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "rewrite soul", date="2026-06-29T09:12:12-07:00")
    sha2 = _git(root, "rev-parse", "--short", "HEAD").strip()
    path.write_text(WORKTREE_TEXT, encoding="utf-8")       # uncommitted edit, like today's checkout
    return {"root": root, "sha1": sha1, "sha2": sha2}


def test_default_filename_and_before_stamp():
    assert default_filename("SOUL.md") == "SOUL.default.md"
    assert default_filename("MEMORY") == "MEMORY.default"
    assert _before_stamp(datetime(2026, 6, 15, 10, 0, 0)) == "2026-06-15T10:00:00-07:00"
    assert _before_stamp("2026-06-15 10:00:00.123456") == "2026-06-15T10:00:00.123456-07:00"
    assert _before_stamp("2026-06-15T10:00:00+00:00") == "2026-06-15T10:00:00+00:00"
    assert _before_stamp(None) is None


def test_historical_row_resolves_git_blob_at_created_at(repo):
    root = repo["root"]
    # between the two commits → first commit's text
    got = resolve_inherited(root, "decider", "SOUL.md", datetime(2026, 6, 15, 10, 0), is_active_row=False)
    assert isinstance(got, InheritedText)
    assert got.resolution == "git-blob-at-created_at"
    assert got.git_sha == repo["sha1"]
    assert got.text == V1_TEXT.strip()                       # .strip() like initialize_prompts._load_agent_file
    assert got.source_path == "agents/decider/SOUL.default.md"
    # after the second commit → second commit's text, not the dirty worktree
    got = resolve_inherited(root, "decider", "SOUL.md", "2026-08-13 12:00:00", is_active_row=False)
    assert got.git_sha == repo["sha2"] and got.text == V2_TEXT.strip()
    # exactly at the commit timestamp is inclusive
    got = git_text_at(root, "agents/decider/SOUL.default.md", datetime(2026, 6, 29, 9, 12, 12))
    assert got.git_sha == repo["sha2"]


def test_row_before_first_commit_falls_back_to_worktree(repo):
    got = resolve_inherited(repo["root"], "decider", "SOUL.md", datetime(2026, 5, 10, 8, 0), is_active_row=False)
    assert got.resolution == "worktree"
    assert got.git_sha is None
    assert got.text == WORKTREE_TEXT.strip()


def test_active_row_uses_worktree_then_live_mirror(repo):
    root = repo["root"]
    got = resolve_inherited(root, "decider", "SOUL.md", datetime(2026, 9, 2, 14, 57), is_active_row=True)
    assert got.resolution == "worktree" and got.text == WORKTREE_TEXT.strip()
    assert got.source_path == "agents/decider/SOUL.default.md"
    live = root / "agents" / "decider" / "SOUL.md"
    live.write_text("  live mirror wins  \n", encoding="utf-8")
    got = resolve_inherited(root, "decider", "SOUL.md", datetime(2026, 9, 2, 14, 57), is_active_row=True)
    assert got.resolution == "live-mirror" and got.text == "live mirror wins"
    assert got.source_path == "agents/decider/SOUL.md"
    # the historical path ignores the (gitignored, uncommitted) live mirror
    got = resolve_inherited(root, "decider", "SOUL.md", datetime(2026, 6, 15), is_active_row=False)
    assert got.resolution == "git-blob-at-created_at"


def test_no_git_falls_back_to_worktree(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    (root / "agents" / "summarizer").mkdir(parents=True)
    (root / "agents" / "summarizer" / "SOUL.default.md").write_text("plain default\n", encoding="utf-8")
    # not a git repository → rev-list fails → worktree
    got = resolve_inherited(root, "summarizer", "SOUL.md", datetime(2026, 6, 15), is_active_row=False)
    assert got.resolution == "worktree" and got.text == "plain default" and got.git_sha is None
    # git binary absent → same fallback, no exception
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    got = resolve_inherited(root, "summarizer", "SOUL.md", datetime(2026, 6, 15), is_active_row=False)
    assert got.resolution == "worktree" and got.text == "plain default"
    # nothing on disk at all → None
    assert resolve_inherited(root, "feedback", "SOUL.md", datetime(2026, 6, 15), is_active_row=False) is None
    assert worktree_text(root, "feedback", "SOUL.md") is None


def test_real_repo_defaults_resolve():
    """The checked-in defaults exist for all three agents (worktree resolution never returns None)."""
    root = Path(__file__).resolve().parent.parent
    for agent_dir in ("decider", "summarizer", "feedback"):
        got = worktree_text(root, agent_dir, "SOUL.md")
        assert got is not None and got.text == got.text.strip() and got.text


# ----------------------------------------------------------------------------- compile_effective (Core track)
def _core_available() -> bool:
    return all(importlib.util.find_spec(m) is not None
               for m in ("policy_graph.compile", "policy_graph.decompose"))


@pytest.mark.skipif(not _core_available(), reason="policy_graph.compile / decompose not present yet (Core track)")
def test_empty_soul_row_compiles_effective_from_inherited_default(repo):
    from policy_graph.compile import compile_build
    from policy_graph.decompose import decompose_row
    from policy_graph.model import RowMeta

    inherited = resolve_inherited(repo["root"], "decider", "SOUL.md", datetime(2026, 6, 15), is_active_row=False)
    fields = {
        "system_prompt": (FIXTURES / "decider_v21_system.md").read_bytes().decode("utf-8"),
        "user_prompt_template": (FIXTURES / "decider_v21_user.md").read_bytes().decode("utf-8"),
        "strategy_directives": (FIXTURES / "decider_v19_sd.md").read_bytes().decode("utf-8"),
        "soul": "",
        "memory": (FIXTURES / "decider_v19_memory.md").read_bytes().decode("utf-8"),
    }
    meta = RowMeta(prompt_version_id=1, created_at=datetime(2026, 6, 15), created_by="system")
    build = decompose_row("DeciderAgent", "cfg_test", 19, fields, meta=meta,
                          inherited={"soul": inherited, "memory": None}, code_nodes=[], ltm_nodes=[],
                          is_margin_account=False)
    inherited_nodes = [n for n in build.nodes if n.owner == "default-file"]
    assert inherited_nodes, "empty stored soul + InheritedText must yield default-file nodes"
    assert all(n.field == "soul" and n.compiled == "effective-only" and n.status == "inherited" for n in inherited_nodes)
    assert all(n.extra.get("inherited_git_sha") == repo["sha1"] for n in inherited_nodes)
    assert build.fields_meta["soul"].get("inherited") is True
    assert "".join(n.text for n in inherited_nodes) == inherited.text
    compiled = compile_build(build)
    assert compiled["soul"] == ""                            # stored bytes untouched
    assert compiled["strategy_directives"] == fields["strategy_directives"]
    assert compiled["memory"] == fields["memory"]
