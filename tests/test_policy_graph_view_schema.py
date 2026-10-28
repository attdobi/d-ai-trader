"""The explorer's presentation vocabulary does not change the policy graph."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from policy_graph.model import EDGE_TYPES

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "static/js/policy-graph-schema.js"
NODE = shutil.which("node") or str(
    Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)


def run_js(script, data=None):
    if not Path(NODE).exists():
        pytest.skip("Node runtime unavailable")
    source = "const S = require(" + json.dumps(str(SCHEMA)) + ");\n" + script
    result = subprocess.run([NODE, "-e", source], input=json.dumps(data), capture_output=True,
                            text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def node(ident, raw_type, field="memory", owner="db", **extra):
    return {"id": ident, "node_type": raw_type, "field": field, "owner": owner, "body": "Meaningful text", **extra}


def test_node_type_is_stable_when_rule_polarity_or_usage_changes():
    fixtures = [
        node("DA.rule", "rule", "strategy_directives", polarity="gate"),
        node("DA.rule", "rule", "strategy_directives", polarity="action", hits={"cited_30d": 200}),
        node("DA.soul.risk_management", "section", "soul", polarity="gate", body="## Risk management\nKeep a cash buffer"),
        node("DA.memory.lessons.kill", "lesson", polarity="gate"),
        node("DA.memory.log.2026_10_28", "entry"),
        node("DA.ltm.42", "ltm", None, "decider_memory"),
        node("DA.factor.fomc", "factor", None, "world"),
        node("DA.code.charter", "code", None, "code"),
    ]
    views = run_js("const data = JSON.parse(require('fs').readFileSync(0, 'utf8')); console.log(JSON.stringify(data.map(S.nodeView)));", fixtures)
    assert [v["type"] for v in views] == ["rule", "rule", "principle", "lesson", "diary", "memory", "context", "scaffold"]
    assert views[0]["color"] == views[1]["color"]
    assert views[0]["group"] == "rules" and views[2]["group"] == "identity"
    assert views[3]["group"] == "learning" and views[5]["group"] == "context"
    assert views[0]["features"]["cited30d"] is None and views[1]["features"]["cited30d"] == 200


def test_hierarchy_containers_are_distinguished_from_meaningful_sections():
    data = [
        node("DA.root", "root", None, "generated"),
        node("DA.memory", "field"),
        node("DA.memory.lessons", "section", body="## Lessons learned\n"),
        node("DA.soul.mission", "section", "soul", body="## Mission\nFind controlled opportunities."),
        node("DA.code", "code", None, "code"),
        node("DA.factor", "factor", None, "world"),
        node("DA.memory.lessons", "section", body="## Lessons learned\n*High-confidence rules earned through P&L.*", has_children=True),
    ]
    result = run_js("const d=JSON.parse(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify(d.map(S.nodeView)));", data)
    assert [r["structural"] for r in result] == [True, True, True, False, True, True, True]
    assert result[3]["type"] == "principle"


def test_titles_are_readable_without_losing_raw_policy_data():
    data = [
        node("DA.rule.kill", "rule", title="3. PRICED KILL — IF D >1.3% THEN pass."),
        node("DA.memory.lessons.regime", "lesson", title="- **#risk-off-entry-pause — Only half size.**"),
        node("DA.soul.mission", "section", "soul", title="Mission (shared across all agents — preserve verbatim)"),
        node("DA.memory.log.2026_10_28", "entry", title="2026-10-28 #FOMC-window"),
        node("DA.code.fomc", "code", None, "code", title="FOMC and CPI WINDOW"),
    ]
    result = run_js("const d=JSON.parse(require('fs').readFileSync(0,'utf8')); const before=JSON.stringify(d); const views=d.map(S.nodeView); console.log(JSON.stringify({titles:views.map(v=>v.title),unchanged:before===JSON.stringify(d)}));", data)
    assert result["titles"] == ["Priced kill", "Risk off entry pause", "Mission", "Oct 28, 2026 · FOMC window", "FOMC and CPI window"]
    assert result["unchanged"]


def test_features_use_explicit_status_without_calling_historical_diary_retired():
    data = [
        node("DA.diary", "entry", status="inert"),
        node("DA.memory.1", "ltm", None, "decider_memory", meta={"active": False}),
        node("DA.rule", "rule", "strategy_directives", locked=True, hits={"cited_30d": 0}),
        node("DA.proposed", "rule", "strategy_directives", ghost="added"),
        node("DA.code.optional", "code", None, "code", status="inactive"),
    ]
    views = run_js("const d=JSON.parse(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify(d.map(S.nodeView)));", data)
    assert views[0]["statusLabel"] == "Historical" and views[0]["features"]["active"]
    assert views[1]["statusLabel"] == "Retired" and not views[1]["features"]["active"]
    assert not views[2]["features"]["editable"] and views[2]["features"]["cited30d"] == 0
    assert views[3]["statusLabel"] == "Proposed" and not views[3]["features"]["editable"]
    assert views[4]["statusLabel"] == "Not used" and not views[4]["features"]["active"]


def test_edges_keep_real_direction_and_relation_subtype():
    result = run_js("console.log(JSON.stringify(Object.keys(S.EDGE_TYPES).map(type=>S.edgeView({edge_type:type,source:{id:'a'},target:'b'}))));")
    by = {r["type"]: r for r in result}
    assert by["subtype_of"]["group"] == "hierarchy" and by["subtype_of"]["label"] == "Part of"
    assert by["includes"]["group"] == by["triggers"]["group"] == "flow"
    assert by["cites"]["directed"] and not by["overlaps"]["directed"]
    assert by["exception_to"]["directed"] and not by["confused_with"]["directed"]
    assert all(r["sourceId"] == "a" and r["targetId"] == "b" for r in result)
    assert by["overlaps"]["dash"] and by["includes"]["dash"] is None


def test_every_canonical_edge_has_an_explicit_visual_definition():
    result = run_js("console.log(JSON.stringify(Object.keys(S.EDGE_TYPES).sort()));")
    assert result == sorted(EDGE_TYPES)


@pytest.mark.parametrize("width", [320, 736, 1024])
def test_group_layout_has_uniform_nonoverlapping_cards_at_supported_widths(width):
    data = [node("DA.root", "root", None, "generated")]
    data += [node(f"DA.soul.p{i}", "section", "soul", title=f"Principle {i}") for i in range(6)]
    data += [node(f"DA.rule.r{i}", "rule", "strategy_directives", title=f"Rule {i}", hits={"cited_30d": i * 100}) for i in range(14)]
    data += [node(f"DA.memory.l{i}", "lesson", title=f"Lesson {i}") for i in range(8)]
    result = run_js(f"const d=JSON.parse(require('fs').readFileSync(0,'utf8')); const before=JSON.stringify(d); const a=S.groupedLayout(d,{width}); console.log(JSON.stringify({{...a,unchanged:before===JSON.stringify(d),repeat:JSON.stringify(a)===JSON.stringify(S.groupedLayout(d,{width}))}}));", data)
    assert result["unchanged"] and result["repeat"]
    assert result["omittedIds"] == ["DA.root"] and len(result["cards"]) == 28
    assert [g["id"] for g in result["groups"]] == ["identity", "rules", "learning"]
    assert {c["width"] for c in result["cards"]} == {result["cardWidth"]}
    assert {c["height"] for c in result["cards"]} == {result["cardHeight"]}
    for card in result["cards"]:
        assert 0 <= card["x"] < card["x"] + card["width"] <= width
        assert 0 <= card["y"] < card["y"] + card["height"] <= result["height"]
    cards = result["cards"]
    for index, card in enumerate(cards):
        for other in cards[index + 1:]:
            assert (card["x"] + card["width"] <= other["x"] or other["x"] + other["width"] <= card["x"]
                    or card["y"] + card["height"] <= other["y"] or other["y"] + other["height"] <= card["y"])


def test_focused_layout_can_keep_containers_and_handles_empty_data():
    result = run_js("const n={id:'DA.root',node_type:'root',owner:'generated'}; console.log(JSON.stringify({empty:S.groupedLayout([],320),focus:S.groupedLayout([n,n],320,{includeGroups:true})}));")
    assert result["empty"]["cards"] == [] and result["empty"]["height"] > 0
    assert len(result["focus"]["cards"]) == 1 and result["focus"]["omittedIds"] == []
