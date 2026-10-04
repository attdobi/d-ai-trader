"""The policy_router package is config-free: it never imports `config` and never reads the environment
(settings, the engine and the HTTP transport are passed in), so policy_graph may import it."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("policy_router", "policy_router.embed", "policy_router.features", "policy_router.model",
           "policy_router.select", "policy_router.llm_tier", "policy_router.labels", "policy_router.dataset",
           "policy_router.nodes", "policy_router.train", "policy_router.runtime", "policy_router.log",
           "policy_router.panel")


def test_importing_the_package_never_imports_config():
    code = "import sys; " + "; ".join(f"import {m}" for m in MODULES) + "; print('config' in sys.modules)"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_sources_never_read_the_environment_or_config():
    for path in sorted((ROOT / "policy_router").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "os.environ" not in src and "os.getenv" not in src and "getenv(" not in src, path.name
        assert "get_current_config_hash" not in src, path.name
        assert not re.search(r"^\s*(import config|from config import)", src, re.M), path.name
