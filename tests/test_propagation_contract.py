from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse(path: str) -> ast.Module:
    source = (REPO_ROOT / path).read_text(encoding="utf-8")
    return ast.parse(source, filename=path)


def test_decider_signature_accepts_run_context_default_none():
    tree = _parse("decider_agent.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "ask_decision_agent":
            arg_names = [a.arg for a in node.args.args]
            assert "run_context" in arg_names
            idx = arg_names.index("run_context")
            defaults = node.args.defaults
            default_offset = idx - (len(arg_names) - len(defaults))
            assert default_offset >= 0
            default_node = defaults[default_offset]
            assert isinstance(default_node, ast.Constant) and default_node.value is None
            return
    raise AssertionError("ask_decision_agent not found")


def test_orchestrator_uses_run_context_create_and_passes_it():
    source = (REPO_ROOT / "d_ai_trader.py").read_text(encoding="utf-8")
    assert "RunContext.create(" in source
    assert "run_context=" in source


def test_orchestrator_no_monkey_patch_of_get_latest_run_id():
    source = (REPO_ROOT / "d_ai_trader.py").read_text(encoding="utf-8")
    assert "decider.get_latest_run_id =" not in source
    assert "original_get_latest_run_id" not in source
