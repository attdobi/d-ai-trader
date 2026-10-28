"""Runtime field disclosures and manual review assembly remain truthful."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from prompt_contracts import prompt_contract
from policy_graph.model import AGENT_PREFIX


def test_weekly_feedback_discloses_only_its_actual_stored_runtime_field():
    contract = prompt_contract("FeedbackAgent", 16)
    assert {key for key, value in contract["fields"].items() if value["used"]} == {"soul"}
    assert "code-owned" in contract["runtime_note"]
    for agent in set(AGENT_PREFIX) - {"FeedbackAgent"}:
        assert all(value["used"] for value in prompt_contract(agent)["fields"].values())
    query = parse_qs(urlparse(contract["compiled_runtime_url"]).query)
    assert query == {"agent": ["FeedbackAgent"], "mode": ["runtime"], "field": ["all"], "version": ["16"]}


def test_legacy_manual_review_resolves_all_stored_fields_before_call():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "feedback_agent.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "generate_ai_feedback_response")
    # Execute the production assembly through the API boundary; no provider or DB.
    captured = {}
    class StopAtAPI(BaseException):
        pass
    def api(system_prompt, user_prompt, *a, **kw):
        captured.update(system=system_prompt, user=user_prompt)
        raise StopAtAPI()
    namespace = {"_canonical_agent_type": lambda a: a, "json": json,
                 "get_agent_model": lambda a: "fixture",
                 "get_reasoning_token_cap": lambda *a: 2000,
                 "_build_feedback_api_params": api}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "feedback_agent.py", "exec"), namespace)
    tracker = SimpleNamespace(get_active_prompt=lambda a: {
        "system_prompt": "Review: {strategy_directives}",
        "user_prompt": "Context {context_data}; metrics {performance_metrics}",
        "strategy_directives": "Approved guidelines", "soul": "Reviewer identity", "memory": "Dated evidence"})
    try:
        namespace[fn.name](tracker, "FeedbackAgent", {"test": True}, {"n": 2})
    except StopAtAPI:
        pass
    assert "{strategy_directives}" not in captured["system"]
    assert all(part in captured["system"] for part in ("Approved guidelines", "Reviewer identity", "Dated evidence"))
    assert '"n": 2' in captured["user"]
