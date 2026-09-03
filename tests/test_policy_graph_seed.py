"""DAI_POLICY_SEED: a new config's v0 comes from the code defaults or from the shipped
agents/*/policy-graph/latest/ graph (compiled from its guideline files)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from policy_graph import seed
from policy_graph.model import AGENT_PREFIX, actor_kind

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {a: {"system_prompt": "SYS", "user_prompt_template": "USER", "strategy_directives": "SD", "soul": "SOUL",
               "memory": "MEM", "description": "v0 default"} for a in AGENT_PREFIX}


def test_normalize_mode():
    assert seed.normalize_mode(None) == "default" and seed.normalize_mode("LATEST") == "latest"
    assert seed.normalize_mode("shipped") == "latest" and seed.normalize_mode("garbage") == "default"


def test_default_mode_keeps_code_defaults():
    rows = seed.seed_rows("default", ROOT, DEFAULTS)
    assert all(r["seed"] == "default" and r["created_by"] == "init_database" and r["system_prompt"] == "SYS" for r in rows.values())


@pytest.mark.skipif(not (ROOT / "agents" / "decider" / "policy-graph" / "latest" / "LATEST.json").exists(),
                    reason="no shipped latest graph in this checkout")
def test_latest_mode_compiles_the_shipped_graph():
    rows = seed.seed_rows("latest", ROOT, DEFAULTS)
    for agent_type in AGENT_PREFIX:
        r = rows[agent_type]
        stamp = seed.latest_stamp(ROOT, agent_type)
        assert r["seed"] == "latest" and r["created_by"] == seed.CREATED_BY_LATEST
        assert r["system_prompt"] != "SYS" and len(r["system_prompt"]) > 200
        assert f"v{stamp['version']}" in r["description"] and stamp["config_hash"] in r["description"]
    assert "PRICED KILL" in rows["DeciderAgent"]["strategy_directives"]
    assert "shipped latest policy" in seed.describe("latest", ROOT)
    assert actor_kind(seed.CREATED_BY_LATEST) == "seed"


def test_latest_mode_falls_back_per_agent(tmp_path):
    # only a Summarizer latest/ exists in this fake checkout
    src = ROOT / "agents" / "summarizer" / "policy-graph" / "latest"
    if not (src / "LATEST.json").exists():
        pytest.skip("no shipped latest graph in this checkout")
    import shutil
    dest = tmp_path / "agents" / "summarizer" / "policy-graph" / "latest"
    shutil.copytree(src, dest)
    rows = seed.seed_rows("latest", tmp_path, DEFAULTS)
    assert rows["SummarizerAgent"]["seed"] == "latest"
    assert rows["DeciderAgent"]["seed"] == "default" and rows["DeciderAgent"]["system_prompt"] == "SYS"
    assert "(no latest/, defaults)" in seed.describe("latest", tmp_path)


def test_latest_fields_none_when_missing(tmp_path):
    assert seed.latest_fields(tmp_path, "DeciderAgent") is None
    (tmp_path / "agents" / "decider" / "policy-graph" / "latest").mkdir(parents=True)
    (tmp_path / "agents" / "decider" / "policy-graph" / "latest" / "LATEST.json").write_text(json.dumps({"version": 5}))
    assert seed.latest_fields(tmp_path, "DeciderAgent") is None
