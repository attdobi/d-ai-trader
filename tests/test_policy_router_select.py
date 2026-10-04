"""policy_router.select: the typed decision and the recall-targeted subgraph (tau, expected recall, pinned
nodes, per-kind floors and caps)."""
from __future__ import annotations

import pytest

from policy_router.select import confidence_of, select_subgraph

ITEMS = [
    ("DA.memory.log.a", "entry", 0.95, 100),
    ("DA.memory.log.b", "entry", 0.60, 200),
    ("DA.ltm.1", "ltm", 0.30, 50),
    ("DA.ltm.2", "ltm", 0.10, 50),
    ("DA.ltm.3", "ltm", 0.05, 50),
]


def _choices(sel):
    return {d.node_id: d.choice for d in sel.decisions}


def test_tau_includes_confident_nodes_and_recall_target_adds_by_descending_p():
    total = sum(p for _i, _k, p, _c in ITEMS)                          # 2.0
    sel = select_subgraph(ITEMS, tau_min=0.9, recall_target=0.0)
    assert sel.include_ids == {"DA.memory.log.a"}
    sel = select_subgraph(ITEMS, tau_min=0.9, recall_target=0.9)        # needs 1.8 of 2.0
    assert sel.include_ids == {"DA.memory.log.a", "DA.memory.log.b", "DA.ltm.1"}
    assert sel.expected_recall == pytest.approx(1.85 / total)
    why = {d.node_id: d.why for d in sel.decisions}
    assert why["DA.memory.log.a"] == "tau" and why["DA.ltm.1"] == "recall" and why["DA.ltm.3"] == "below_target"
    sel = select_subgraph(ITEMS, tau_min=1.01, recall_target=1.0)        # everything with p > 0
    assert len(sel.included) == 5 and sel.expected_recall == pytest.approx(1.0)


def test_typed_decision_shape_and_confidence():
    sel = select_subgraph(ITEMS, tau_min=0.5, recall_target=0.5)
    d = sel.decisions[0].to_dict()
    assert set(d) >= {"node_id", "p", "choice", "confidence", "kind", "chars"}
    assert d["choice"] in ("include", "exclude")
    assert confidence_of(0.5) == 0 and confidence_of(1.0) == 1 and confidence_of(0.1) == pytest.approx(0.8)
    assert [x.p for x in sel.decisions] == sorted((x.p for x in sel.decisions), reverse=True)
    assert sel.chars_routable == 450 and sel.chars_selected == sum(x.chars for x in sel.included)


def test_pinned_nodes_are_always_included_and_left_out_of_expected_recall():
    items = ITEMS + [("DA.directives.strategy.priced_kill", "rule", 0.01, 400)]
    sel = select_subgraph(items, pinned_ids={"DA.directives.strategy.priced_kill"}, tau_min=0.9, recall_target=0.0)
    pinned = [d for d in sel.decisions if d.pinned]
    assert [d.node_id for d in pinned] == ["DA.directives.strategy.priced_kill"]
    assert pinned[0].choice == "include" and pinned[0].why == "pinned"
    assert sel.chars_selected == 100                                   # pinned chars are not "selected routable" chars
    assert sel.expected_recall == pytest.approx(0.95 / 2.0)


def test_min_per_kind_floor_and_max_per_kind_cap():
    sel = select_subgraph(ITEMS, tau_min=0.9, recall_target=0.0, min_per_kind={"ltm": 2})
    assert {"DA.ltm.1", "DA.ltm.2"} <= sel.include_ids and "DA.ltm.3" not in sel.include_ids
    sel = select_subgraph(ITEMS, tau_min=0.01, recall_target=1.0, max_per_kind={"ltm": 1})
    c = _choices(sel)
    assert c["DA.ltm.1"] == "include" and c["DA.ltm.2"] == "exclude" and c["DA.ltm.3"] == "exclude"
    assert sel.capped == {"ltm": ["DA.ltm.2", "DA.ltm.3"]}
    assert {d.node_id: d.why for d in sel.decisions}["DA.ltm.2"] == "cap"
    assert sel.expected_recall == pytest.approx(1.85 / 2.0)            # the recall actually reached under the cap
    # a cap wins over a floor
    sel = select_subgraph(ITEMS, tau_min=0.9, recall_target=0.0, min_per_kind={"ltm": 3}, max_per_kind={"ltm": 1})
    assert sum(1 for d in sel.included if d.kind == "ltm") == 1


def test_empty_and_zero_mass_inputs():
    sel = select_subgraph([], tau_min=0.5, recall_target=0.98)
    assert sel.decisions == [] and sel.expected_recall == 1.0
    sel = select_subgraph([("a", "ltm", 0.0, 10)], tau_min=0.5, recall_target=0.98)
    assert sel.include_ids == set() and sel.expected_recall == 1.0
    sel = select_subgraph([{"node_id": "a", "kind": "entry", "p": 0.7, "chars": 5}], tau_min=0.5)
    assert sel.include_ids == {"a"}
