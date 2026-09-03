"""Inherited defaults — what prompt_manager substitutes for an empty soul/memory column.

initialize_prompts._load_agent_file(agent, filename) returns, stripped, the first of
  agents/<dir>/<filename>            (live mirror, gitignored)
  agents/<dir>/<stem>.default.<ext>  (committed seed)
This module reproduces that resolution WITHOUT importing initialize_prompts (which imports
config). For historical rows it approximates the text the row saw at creation time from git:
the last commit of the default file at or before `created_at`. Git unavailable, not a repo,
or no commit before the row → worktree file with resolution 'worktree'.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .model import InheritedText

GIT_TIMEOUT_S = 10
# DB timestamps are naive Pacific; the spec fixes the offset used for `git --before`.
DEFAULT_UTC_OFFSET = "-07:00"


def default_filename(filename: str) -> str:
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        return f"{stem}.default.{ext}"
    return f"{filename}.default"


def _read_stripped(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _git(repo_root: Path, *args: str) -> Optional[str]:
    """Run git in repo_root; None on any failure (missing binary, not a repo, timeout, non-zero)."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo_root), capture_output=True, timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def _before_stamp(created_at) -> Optional[str]:
    if created_at is None:
        return None
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            return created_at.isoformat() + DEFAULT_UTC_OFFSET
        return created_at.isoformat()
    s = str(created_at).strip()
    if not s:
        return None
    if s.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", s):
        return s
    return s.replace(" ", "T") + DEFAULT_UTC_OFFSET


def worktree_text(repo_root: Path, agent_dir: str, filename: str) -> Optional[InheritedText]:
    """_load_agent_file semantics on the checkout: live mirror first, then the committed default."""
    base = Path(repo_root) / "agents" / agent_dir
    live = base / filename
    if live.exists():
        text = _read_stripped(live)
        if text is not None:
            return InheritedText(text=text, source_path=f"agents/{agent_dir}/{filename}",
                                 git_sha=None, resolution="live-mirror")
    default = base / default_filename(filename)
    if default.exists():
        text = _read_stripped(default)
        if text is not None:
            return InheritedText(text=text, source_path=f"agents/{agent_dir}/{default.name}",
                                 git_sha=None, resolution="worktree")
    return None


def git_text_at(repo_root: Path, rel_path: str, created_at) -> Optional[InheritedText]:
    """The committed default file as of `created_at` (git rev-list --before + git show)."""
    stamp = _before_stamp(created_at)
    if stamp is None:
        return None
    out = _git(Path(repo_root), "rev-list", "-1", f"--before={stamp}", "HEAD", "--", rel_path)
    sha = (out or "").strip()
    if not sha:
        return None
    blob = _git(Path(repo_root), "show", f"{sha}:{rel_path}")
    if blob is None:
        return None
    short = (_git(Path(repo_root), "rev-parse", "--short", sha) or sha[:8]).strip()
    return InheritedText(text=blob.strip(), source_path=rel_path, git_sha=short,
                         resolution="git-blob-at-created_at")


def resolve_inherited(repo_root: Path, agent_dir: str, filename: str, created_at, *,
                      is_active_row: bool) -> Optional[InheritedText]:
    """Text prompt_manager would substitute for an empty column of this row.

    Active row → the checkout (live mirror, else default file). Historical row → the default
    file's git blob at created_at, falling back to the checkout. None when no file exists."""
    if not is_active_row:
        found = git_text_at(repo_root, f"agents/{agent_dir}/{default_filename(filename)}", created_at)
        if found is not None:
            return found
    return worktree_text(repo_root, agent_dir, filename)
