"""Launcher text matches the real schedule, the default model is gpt-5.6-terra, -v/-P are deprecated
(still take a value), dead knobs are gone, and the older OpenAI models carry real rates."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "start_d_ai_trader.sh"


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def test_launcher_parses():
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True, timeout=20)
    subprocess.run(["bash", "-n", str(REPO_ROOT / "start_schwab_live_view.sh")], check=True, timeout=20)


def test_deprecated_flags_take_a_value_and_print_one_notice():
    # --help exits inside the argument loop, before anything is created or started
    out = subprocess.run(["bash", str(LAUNCHER), "-v", "v12", "--prompt-profile", "gpt-pro", "--help"],
                         capture_output=True, text=True, timeout=20, check=True).stdout
    lines = out.splitlines()
    assert lines[0] == "⚠️  -v is deprecated and ignored (the active prompt version comes from the database)"
    assert lines[1] == "⚠️  --prompt-profile is deprecated and ignored (no code reads a prompt profile)"
    assert "Global AI model (default: gpt-5.6-terra)" in out


def test_launcher_defaults_and_schedule_text():
    sh = _read("start_d_ai_trader.sh")
    assert 'MODEL="gpt-5.6-terra"' in sh and 'MODEL="gpt-4o"' not in sh
    assert "BEST for trading" not in sh
    for stale in ("1:30 PM PT", "daily performance analysis", "6:35 AM - 1:00 PM PT", "(daily)"):
        assert stale not in sh
    assert "weekly, Thursday 8:30 PM ET" in sh
    assert "until 5:25 PM ET" in sh
    assert "DAI_PROMPT_VERSION" not in sh and "DAI_PROMPT_PROFILE" not in sh


@pytest.mark.parametrize("script", sorted(p.name for p in REPO_ROOT.glob("*.sh")))
def test_no_shell_script_exports_dai_disable_uc(script):
    assert not re.search(r"\bexport\s+DAI_DISABLE_UC\b", _read(script))
    assert "DAI_DISABLE_UC" not in _read(script)


def test_dead_max_trades_parse_is_gone():
    assert "DAI_MAX_TRADES" not in _read("decider_agent.py")
    assert "MAX_TRADES" not in _read("decider_agent.py")


def test_orchestrator_text_matches_the_schedule():
    src = _read("d_ai_trader.py")
    doc = src.split('"""', 2)[1]          # the module docstring (after the bootstrap block)
    assert "hourly" not in doc and "4:30pm ET" not in doc
    assert "Thursday 8:30pm ET" in doc and "5:25pm ET" in doc
    assert "4:30 PM ET - Performance feedback" not in src
    assert "Thursday 8:30 PM ET - Performance feedback" in src
    assert "9:35 AM - 4:00 PM ET" not in src


def test_older_model_rates_are_filled():
    pricing = json.loads(_read("model_pricing.json"))
    assert pricing["gpt-4o"] == {"input": 2.50, "output": 10.00}
    assert pricing["gpt-4o-mini"] == {"input": 0.15, "output": 0.60}
    assert pricing["gpt-4.1"] == {"input": 2.00, "output": 8.00}
    assert pricing["gpt-5.6-terra"] == {"input": 2.00, "output": 12.00}
