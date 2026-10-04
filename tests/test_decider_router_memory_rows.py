"""The Decider's LESSONS block under an active policy router: the router's kept memory rows replace today's
fixed top-N rows only when it actually scored memory rows this cycle. An entry-only routable set, or a failed
get_all_active_memories (no ltm nodes), serves today's rows unchanged — never an empty LESSONS block."""
from __future__ import annotations

import ast
from pathlib import Path

from tests.test_policy_router_runtime import embedder, fakes, make_artifact, nodes, settings, write_artifact
from policy_router.runtime import route_cycle

ROOT = Path(__file__).resolve().parents[1]
TODAY = [{"id": 3, "text": "today's top-N row"}, {"id": 4, "text": "another top-N row"}]
ALL_ROWS = {"DA.ltm.7": {"id": 7, "text": "QCOM chase"}, "DA.ltm.8": {"id": 8, "text": "zebra giraffe"}}


def _helper():
    """Compile decider_agent._router_memory_rows without importing decider_agent (it imports config)."""
    tree = ast.parse((ROOT / "decider_agent.py").read_text(encoding="utf-8"))
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_router_memory_rows"]
    assert len(fn) == 1
    ns = {}
    exec(compile(ast.Module(body=fn, type_ignores=[]), "decider_agent.py", "exec"), ns)
    return ns["_router_memory_rows"]


def _active(tmp_path, cycle_nodes, *, routable):
    write_artifact(tmp_path, make_artifact(routable=routable))
    r = route_cycle(settings(tmp_path, DAI_POLICY_ROUTER="active", DAI_ROUTER_ROUTABLE=",".join(routable)),
                    fakes.context(), cycle_nodes, embedder=embedder())
    r.extras["ltm_rows"] = {i: m for i, m in ALL_ROWS.items() if i in {n.node_id for n in cycle_nodes}}
    assert r.active
    return r


def test_entry_only_active_router_keeps_todays_memory_rows(tmp_path):
    r = _active(tmp_path, nodes(), routable=("entry",))
    assert r.ltm_selected_ids() == [] and r.ltm_tail_line() == ""
    assert _helper()(r, TODAY) == (TODAY, "")


def test_active_router_without_memory_rows_keeps_todays_rows(tmp_path):
    # get_all_active_memories swallowed a DB error and returned [] → no ltm nodes reach the router
    no_ltm = [n for n in nodes() if n.kind != "ltm"]
    r = _active(tmp_path, no_ltm, routable=("entry", "ltm"))
    assert _helper()(r, TODAY) == (TODAY, "")


def test_active_router_that_scored_memory_rows_serves_its_kept_rows(tmp_path):
    r = _active(tmp_path, nodes(), routable=("entry", "ltm"))
    rows, tail = _helper()(r, TODAY)
    assert r.ltm_selected_ids() and rows == [ALL_ROWS[i] for i in r.ltm_selected_ids()] and tail == r.ltm_tail_line()
    assert all(m not in rows for m in TODAY)


def test_no_router_or_shadow_router_keeps_todays_rows(tmp_path):
    helper = _helper()
    assert helper(None, TODAY) == (TODAY, "")
    write_artifact(tmp_path, make_artifact())
    shadow = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder())
    assert not shadow.active and helper(shadow, TODAY) == (TODAY, "")


def test_decider_routes_its_memory_rows_through_the_helper():
    tree = ast.parse((ROOT / "decider_agent.py").read_text(encoding="utf-8"))
    ask = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "ask_decision_agent")
    calls = [n for n in ast.walk(ask) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_router_memory_rows"]
    assert len(calls) == 1
    assert not [n for n in ast.walk(ask) if isinstance(n, ast.Attribute) and n.attr == "ltm_selected_ids"]
