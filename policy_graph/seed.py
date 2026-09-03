"""Where a NEW config's v0 policy comes from: the code defaults or the shipped latest graph.

    DAI_POLICY_SEED=default   v0 = initialize_prompts.DEFAULT_PROMPTS (the committed baseline)
    DAI_POLICY_SEED=latest    v0 = agents/<dir>/policy-graph/latest/ — the active policy the
                              repository was pushed with, compiled from its guideline files

The choice only applies when a config has no prompt rows yet (a fresh checkout, a new config
hash). Rows seeded from the latest graph carry created_by = 'seed_latest' so later startups never
re-sync them to the code defaults. `init_database.seed_v0_prompts` and
`prompt_manager.initialize_config_prompts` both call `seed_rows`.

stdlib only; the environment is read by the CALLER (`mode` is a parameter here).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .compile import compile_stored, read_version_dir
from .model import AGENT_LABEL, AGENT_PREFIX, FIELDS
from .store import latest_root

SEED_MODES = ("default", "latest")
SEED_ENV = "DAI_POLICY_SEED"
CREATED_BY_LATEST = "seed_latest"


def normalize_mode(raw) -> str:
    v = str(raw or "").strip().lower()
    if v in ("latest", "shipped", "current"):
        return "latest"
    return "default"


def latest_stamp(repo_root: Path, agent_type: str) -> Optional[dict]:
    path = latest_root(Path(repo_root), agent_type) / "LATEST.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_fields(repo_root: Path, agent_type: str) -> Optional[tuple]:
    """(fields, stamp) compiled from agents/<dir>/policy-graph/latest/v<N>/, or None when absent."""
    stamp = latest_stamp(repo_root, agent_type)
    if not stamp:
        return None
    path = latest_root(Path(repo_root), agent_type) / f"v{int(stamp.get('version', 0))}"
    if not (path / "manifest.json").is_file():
        return None
    version = read_version_dir(path)
    stored = compile_stored(version)
    fields = {f: (stored.get(f) or "") for f in FIELDS}
    if not fields["system_prompt"] or not fields["user_prompt_template"]:
        return None
    return fields, stamp


def seed_rows(mode: str, repo_root: Path, default_rows: dict) -> dict:
    """{agent_type: {system_prompt, user_prompt_template, strategy_directives, soul, memory,
    description, created_by, seed}} for the agents in `default_rows` (the code defaults, already
    normalised). In 'latest' mode an agent falls back to its default when no latest/ copy exists."""
    mode = normalize_mode(mode)
    out = {}
    for agent_type, payload in default_rows.items():
        row = dict(payload)
        row["created_by"] = "init_database"
        row["seed"] = "default"
        if mode == "latest" and agent_type in AGENT_PREFIX:
            got = latest_fields(repo_root, agent_type)
            if got is not None:
                fields, stamp = got
                row.update(fields)
                row["description"] = (f"v0 seeded from the shipped latest policy — {AGENT_LABEL[agent_type]} "
                                      f"v{stamp.get('version')} of config {stamp.get('config_hash')}")
                row["created_by"] = CREATED_BY_LATEST
                row["seed"] = "latest"
        out[agent_type] = row
    return out


def describe(mode: str, repo_root: Path) -> str:
    mode = normalize_mode(mode)
    if mode == "default":
        return "v0 = code defaults (initialize_prompts.DEFAULT_PROMPTS / agents/*/policy-graph/baseline)"
    parts = []
    for agent_type in AGENT_PREFIX:
        stamp = latest_stamp(repo_root, agent_type)
        parts.append(f"{AGENT_LABEL[agent_type]} v{stamp.get('version')}" if stamp else f"{AGENT_LABEL[agent_type]} (no latest/, defaults)")
    return "v0 = shipped latest policy (" + ", ".join(parts) + ")"


__all__ = ["SEED_MODES", "SEED_ENV", "CREATED_BY_LATEST", "normalize_mode", "latest_fields", "latest_stamp",
           "seed_rows", "describe"]
