"""Static safety-net tests for centralized startup model initialization."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENV_OVERRIDE_BLOCK = 'if _os.environ.get("DAI_GPT_MODEL")'
TARGET_MODULES = [
    "main.py",
    "d_ai_trader.py",
    "decider_agent.py",
    "feedback_agent.py",
    "dashboard_server.py",
]


@pytest.mark.parametrize("module_name", TARGET_MODULES)
def test_no_legacy_per_module_dai_gpt_model_override_block(module_name):
    source_path = REPO_ROOT / module_name
    source = source_path.read_text(encoding="utf-8")

    assert LEGACY_ENV_OVERRIDE_BLOCK not in source, (
        f"{module_name} still contains legacy per-module DAI_GPT_MODEL override block; "
        "model selection should come from centralized config startup path."
    )
