"""Layers (policy / scaffold / context), plain kinds, coarse edge kinds, the last-run served lookup and the
plain-gate style lint."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine

from policy_graph import citations as C
from policy_graph import proposals as P
from policy_graph.assembly import Selected
from policy_graph.model import EDGE_TYPES, Node, edge_kind, kind_of, layer_of


def _n(nid, node_type, owner="db", field="strategy_directives", parent=None):
    return Node(id=nid, agent="DeciderAgent", title=nid, node_type=node_type, parent=parent or ".".join(nid.split(".")[:-1]),
                field=field, body="x", owner=owner)


def test_layers_and_kinds():
    assert layer_of(_n("DA.directives.strategy.regime_gate", "rule")) == "policy"
    assert kind_of(_n("DA.directives.strategy.regime_gate", "rule")) == "gate"
    assert layer_of(_n("DA.memory.lessons.regime", "lesson", field="memory")) == "policy"
    assert kind_of(_n("DA.memory.log.2026_09_02", "entry", field="memory")) == "diary entry"
    assert kind_of(_n("DA.directives.reminder", "reminder")) == "weekly reminder"
    assert layer_of(_n("DA.soul.core_philosophy", "section", owner="default-file", field="soul")) == "policy"
    assert layer_of(_n("DA.directives", "field")) == "policy" and kind_of(_n("DA.directives", "field")) == "policy file"
    assert layer_of(_n("DA.root", "root", owner="generated", field=None)) == "scaffold"
    assert layer_of(_n("DA.template.system", "template", field="system_prompt")) == "scaffold"
    assert kind_of(_n("DA.template.system", "template", field="system_prompt")) == "prompt template"
    assert layer_of(_n("DA.code.deploy_policy", "code", owner="code", field=None)) == "scaffold"
    assert kind_of(_n("DA.code.deploy_policy", "code", owner="code", field=None)) == "code-owned prompt text"
    assert kind_of(_n("DA.code", "code", owner="code", field=None, parent="DA.root")) == "code-owned blocks"
    assert layer_of(_n("DA.runtime.inputs", "data", owner="runtime", field=None)) == "scaffold"
    assert layer_of(_n("DA.ltm.20", "ltm", owner="decider_memory", field=None)) == "context"
    assert kind_of(_n("DA.ltm.20", "ltm", owner="decider_memory", field=None)) == "memory row"
    assert layer_of(_n("DA.ltm", "section", owner="generated", field=None)) == "context"
    assert kind_of(_n("DA.ltm", "section", owner="generated", field=None)) == "memory rows"
    assert layer_of(_n("DA.factor.fomc.2026_09_16", "factor", owner="world", field=None)) == "context"
    assert kind_of(_n("DA.factor", "factor", owner="world", field=None)) == "world factors"
    assert layer_of(_n("DA.ticker.tsla", "ticker", owner="generated", field=None)) == "context"


def test_edge_kinds_cover_every_type():
    for t in EDGE_TYPES:
        assert edge_kind(t) in ("part_of", "feeds", "related")
    assert edge_kind("subtype_of") == "part_of" and edge_kind("triggers") == "feeds" and edge_kind("constrains") == "feeds"
    assert edge_kind("overlaps") == "related" and edge_kind("nonsense") == "related"


def test_last_run_served_sqlite():
    engine = create_engine("sqlite://")
    C.ensure_hits_schema(engine)
    C.ensure_runs_schema(engine)
    assert C.last_run_served(engine, "h") is None
    at1, at2 = datetime(2026, 9, 15, 10), datetime(2026, 9, 16, 10)
    C.record_served(engine, "h", "DeciderAgent", 28, "r1", [Selected("DA.a", "core", "x")], decided_at=at1)
    C.record_run(engine, "h", "DeciderAgent", 28, "r1", served=1, dropped=0, chars_full=10, chars_served=10, routes={"core": 1}, context={}, decided_at=at1)
    C.record_served(engine, "h", "DeciderAgent", 28, "r2", [Selected("DA.a", "core", "x"), Selected("DA.code.x", "code", "")], decided_at=at2)
    C.record_cited(engine, "h", "DeciderAgent", 28, "r2", [{"action": "buy", "ticker": "T", "reason": "y [cites: DA.a]"}], decided_at=at2)
    C.record_run(engine, "h", "DeciderAgent", 28, "r2", served=2, dropped=3, chars_full=100, chars_served=90, routes={"core": 1, "code": 1}, context={"regime": "MIXED"}, decided_at=at2)
    lr = C.last_run_served(engine, "h")
    assert lr["run_id"] == "r2" and lr["served"] == {"DA.a": "core", "DA.code.x": "code"} and lr["cited"] == ["DA.a"]
    assert lr["dropped"] == 3 and lr["routes"] == {"core": 1, "code": 1} and lr["context"] == {"regime": "MIXED"}
    assert lr["decided_at"].startswith("2026-09-16")
    engine.dispose()


def test_style_check_flags_dense_gates():
    dense = P.FileChange(id="DA.directives.strategy.x", action="add", primary=True, body=(
        "9. EVENT GATE — read the block (every cycle). IF a THEN b. IF c THEN d (see above). " + "x" * 260))
    plain = P.FileChange(id="DA.directives.strategy.y", action="add", primary=True, body=(
        "10. EARNINGS CANDIDATE — IF a BUY candidate reports earnings within the next 5 sessions THEN reject it. "
        "Otherwise next gate. Falsified if 20 such candidates average better than +1% over their next 5 sessions."))
    lesson = P.FileChange(id="DA.memory.lessons.z", action="add", primary=False, body="- **#tag — short.** One sentence (with an aside) (and another).")
    prose = P.FileChange(id="DA.soul.risk_management", action="edit", primary=False, body="## Risk Management\n- a bullet (with parens) (twice) " + "y" * 400)
    removed = P.FileChange(id="DA.directives.strategy.old", action="remove", primary=False, body="")
    w = P.style_check([dense, plain, lesson, prose, removed])
    by = {}
    for x in w:
        by.setdefault(x["id"], []).append(x["warning"])
    assert len(by["DA.directives.strategy.x"]) == 4          # long, two conditions, parentheses, no falsifier
    assert "DA.directives.strategy.y" not in by
    assert by["DA.memory.lessons.z"] == ["lesson has 2 parenthetical asides; move the numbers into the sentence"]
    assert "DA.soul.risk_management" not in by and "DA.directives.strategy.old" not in by
