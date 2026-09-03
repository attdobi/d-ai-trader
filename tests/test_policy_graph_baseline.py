"""The committed baseline graph (agents/*/policy-graph/baseline/v0) must compile to today's
initialize_prompts.DEFAULT_PROMPTS byte-for-byte, and regenerating it must be byte-stable."""
from __future__ import annotations

import filecmp
from pathlib import Path

import pytest

from policy_graph import baseline
from policy_graph.compile import compile_stored, read_version_dir
from policy_graph.model import AGENT_PREFIX

ROOT = Path(__file__).resolve().parent.parent


def test_committed_baseline_matches_default_prompts():
    problems = baseline.verify_baseline(ROOT)
    assert not problems, ("committed baseline is stale — run `./dai/bin/python -m policy_graph.backfill --baseline`: "
                          + "; ".join(f"{a}: {p}" for a, p in problems))


def test_baseline_is_reproducible(tmp_path):
    baseline.write_baseline(tmp_path)
    for agent_type in AGENT_PREFIX:
        a = baseline.baseline_root(ROOT, agent_type) / "v0"
        b = baseline.baseline_root(tmp_path, agent_type) / "v0"
        cmp = filecmp.dircmp(a, b)
        assert not cmp.diff_files and not cmp.left_only and not cmp.right_only, (agent_type, cmp.diff_files, cmp.left_only, cmp.right_only)
        v = read_version_dir(b)
        assert v.manifest["config_hash"] == "baseline" and v.manifest["created_by"] == "init_database"
        assert "materialized_at" not in v.manifest and "pid" not in v.manifest
        assert compile_stored(v)["system_prompt"] == baseline.baseline_fields(agent_type)["system_prompt"]


def test_baseline_has_no_lock_or_memory_rows():
    for agent_type in AGENT_PREFIX:
        root = baseline.baseline_root(ROOT, agent_type)
        assert not (root / ".lock").exists()
        assert not (root / "_ltm").exists() or not any((root / "_ltm").iterdir())
