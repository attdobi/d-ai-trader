"""Hosted shadow work cannot hold up or control the trading prompt."""
from __future__ import annotations

import ast
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from policy_router import shadow_bridge as bridge
from policy_router.features import CycleContext
from policy_router.nodes import RouterNode
from policy_safety import blanket_entry_vetoes

ROOT = Path(__file__).resolve().parents[1]


def test_slow_request_logs_actual_served_ids_without_waiting_or_queuing_more():
    release, started, recorded = Event(), Event(), Event()
    writes = []
    result = object()

    def score():
        started.set()
        assert release.wait(2)
        return result

    def record(*args, **kwargs):
        writes.append((args, kwargs))
        recorded.set()

    job = bridge.submit_shadow(score)
    try:
        assert started.wait(1)
        ids = {"DA.ltm.1"}
        bridge.record_when_ready(job, "engine", "cfg", 59, "run", served_ids=ids,
                                 local_result="local", source_input_id=148, recorder=record)
        ids.add("not_actually_served")
        assert not writes
        assert bridge.submit_shadow(score, log=lambda *_a: None) is None
    finally:
        release.set()
    assert recorded.wait(1)
    assert writes[0][0] == ("engine", "cfg", 59, "run", result)
    assert writes[0][1] == {"served_ids": frozenset({"DA.ltm.1"}), "local_result": "local", "source_input_id": 148}


def test_failure_is_contained_without_printing_remote_exception_values():
    logs, writes = [], []
    done = Event()

    def fail():
        raise RuntimeError("sensitive-driver-or-authorization-value")

    def log(value):
        logs.append(value)
        done.set()

    job = bridge.submit_shadow(fail)
    bridge.record_when_ready(job, None, "cfg", 59, "run", recorder=lambda *a, **k: writes.append(a), log=log)
    assert done.wait(1)
    assert writes == []
    assert logs == ["Decisions comparison audit unavailable (RuntimeError)"]


def test_already_completed_request_still_dispatches_audit_off_the_trading_path():
    release, entered, written = Event(), Event(), Event()
    ready = Future()
    ready.set_result("scored")

    def slow_write(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        written.set()

    try:
        bridge.record_when_ready(ready, None, "cfg", 59, "run", recorder=slow_write)
        assert entered.wait(1)
        assert not written.is_set()
    finally:
        release.set()
    assert written.wait(1)


@pytest.mark.parametrize("remote_mode,local_mode,queued", [
    ("off", "shadow", False), ("active", "shadow", False),
    ("shadow", "off", True), ("shadow", "shadow", True),
])
def test_decider_bridge_is_independent_of_local_mode_and_keeps_hard_policy_pinned(monkeypatch, remote_mode, local_mode, queued):
    """Execute the production integration helper with fake IO, never config/DB/API."""
    import os
    import sys
    import policy_router.nodes as N
    import policy_router.runtime as R
    import policy_graph.service as S
    import policy_graph.assembly as A
    import policy_graph.compile as C
    entry = RouterNode("DA.memory.log.recent", "entry", "Useful current diary", 20)
    lesson = RouterNode("DA.memory.lessons.stop", "lesson", "Never widen a priced kill", 25)
    memory = RouterNode("DA.ltm.9", "ltm", "A relevant holding lesson", 20)
    retired = RouterNode("DA.ltm.42", "ltm", "IF INDEX REGIME is RISK-OFF THEN pass.", 40)

    def node(ident, kind, body, owner="db"):
        return SimpleNamespace(id=ident, node_type=kind, body=body, owner=owner, field="memory", order=1)

    version = SimpleNamespace(nodes={n.id: n for n in (
        node(entry.node_id, "entry", entry.text),
        node(lesson.node_id, "lesson", lesson.text),
        node("DA.directives.strategy.priced_kill", "rule", "D >1.3% rejects a candidate"),
        node("DA.code.opportunity_charter", "code", "Selective half-size opportunities", "code"),
        node("DA.memory", "field", "Memory"),
    )})
    monkeypatch.setenv("DAI_POLICY_ROUTER", local_mode)
    monkeypatch.setenv("DAI_DECISIONS_ROUTER", remote_mode)
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(api_key="fake-key"))
    monkeypatch.setitem(sys.modules, "decider_memory", SimpleNamespace(
        get_all_active_memories=lambda cfg: [{"id": 9}, {"id": 42}],
        get_relevant_memories=lambda cfg, **kw: [{"id": 9}]))
    monkeypatch.setattr(N, "version_nodes", lambda *a: [entry, lesson])
    monkeypatch.setattr(N, "ltm_row_nodes", lambda *a: [memory, retired])
    monkeypatch.setattr(S, "ensure_materialized", lambda *a, **k: None)
    monkeypatch.setattr(C, "read_version_dir", lambda *a: version)
    monkeypatch.setattr(A, "select", lambda *a: ([SimpleNamespace(node_id=entry.node_id)], []))
    local = SimpleNamespace(extras={})
    monkeypatch.setattr(R, "route_cycle", lambda settings, *a, **kw: None if settings.mode == "off" else local)
    submissions = []
    monkeypatch.setattr(bridge, "submit_shadow", lambda *a, **kw: submissions.append((a, kw)) or "job")
    tree = ast.parse((ROOT / "decider_agent.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_policy_router_cycle")
    ns = {"__file__": str(ROOT / "decider_agent.py"), "os": os, "datetime": datetime,
          "engine": object(), "IS_MARGIN_ACCOUNT": False, "get_current_config_hash": lambda: "cfg",
          "blanket_entry_vetoes": blanket_entry_vetoes}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "decider_agent.py", "exec"), ns)
    sink = {}
    actual = ns[function.name](59, "run", regime="RISK-OFF", holdings=[], watchlist=["GM"],
                               quarantined=[], shadow_sink=sink)
    assert actual is (None if local_mode == "off" else local)
    assert bool(submissions) is queued
    if queued:
        args, kwargs = submissions[0]
        assert isinstance(args[2], CycleContext)
        assert {n.node_id for n in args[3]} == {entry.node_id, memory.node_id}
        assert "DA.directives.strategy.priced_kill" in kwargs["pinned_ids"]
        assert lesson.node_id in kwargs["pinned_ids"]
        assert "OPPORTUNITY CHARTER" in kwargs["pinned_policy"]
        assert sink["flat_ids"] == {entry.node_id}
        assert sink["job"] == "job"


def test_comparison_schema_is_part_of_startup_migration():
    source = (ROOT / "init_database.py").read_text()
    assert 'ensure_table(conn, stats, "policy_router_comparisons", _COMPARISON_DDL)' in source
