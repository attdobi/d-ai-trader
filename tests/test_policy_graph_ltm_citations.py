"""Long-term memory rows (decider_memory → DA.ltm.<id>) are citable: rendered with their ⟨id⟩ tag,
listed in the GUIDELINE INDEX, accepted by validation and the repair pass, and logged as cited hits
on their 'ltm' served row (SQLite; decider_memory is imported with a stub config)."""
from __future__ import annotations

import importlib
import sys
import types

import pytest
from sqlalchemy import create_engine, text

from policy_graph import citations as C
from policy_graph.assembly import Selected, health_tag
from policy_graph.lessons import format_memory_line, ltm_nodes, ltm_title

ROWS = [
    {"id": 18, "content": "REGIME GATE (read the INDEX REGIME line first): RISK-ON = up to 3 new BUYs at full rails, "
                          "MIXED = 2 at half size, RISK-OFF = 1.", "kind": "rule", "ticker": None, "weight": 2.0},
    {"id": 4, "content": "Do NOT churn your own fresh entries.\nSecond line.", "kind": None, "ticker": "irdm", "weight": 1.0},
]


@pytest.fixture
def mem(monkeypatch):
    stub = types.ModuleType("config")
    stub.engine = None
    monkeypatch.setitem(sys.modules, "config", stub)
    sys.modules.pop("decider_memory", None)
    mod = importlib.import_module("decider_memory")
    yield mod
    sys.modules.pop("decider_memory", None)


def test_lessons_block_carries_each_rows_citation_tag(mem):
    plain = mem.format_long_term_memory(ROWS)
    # without a tag the block is unchanged: each row is exactly the graph node's body
    header = "# LESSONS (long-term memory — hard rules earned from P&L; OBEY them):"
    assert plain == "\n".join([header] + [format_memory_line(r) for r in ROWS])
    health = {"DA.ltm.18": {"7d": {"cited": 1}, "30d": {"cited": 2}, "90d": {"cited": 5}}}
    tagged = mem.format_long_term_memory(ROWS, cite_tag=lambda m: health_tag(f"DA.ltm.{m['id']}", health))
    lines = tagged.splitlines()
    assert lines[0].startswith("# LESSONS (long-term memory")
    assert lines[1] == format_memory_line(ROWS[0]) + " ⟨DA.ltm.18 · cited 7d/30d/90d: 1/2/5⟩"
    assert tagged.endswith("Second line. ⟨DA.ltm.4⟩")
    # a failing tag never breaks the block
    def _boom(_m):
        raise RuntimeError("x")
    assert mem.format_long_term_memory(ROWS, cite_tag=_boom) == plain
    assert mem.format_long_term_memory([], cite_tag=_boom) == ""


def test_ltm_index_lines_join_the_guideline_index():
    lines = C.ltm_index_lines(ROWS + [{"id": 18, "content": "dup"}, {"content": "no id"}, "junk", {"id": "x", "content": "bad"}])
    assert lines == [f"DA.ltm.18 — {ltm_title(ROWS[0])}", "DA.ltm.4 — Do NOT churn your own fresh entries."]
    assert len(ltm_title(ROWS[0])) <= 72 and ltm_title(ROWS[0]).endswith("…")
    # the titles match the graph nodes'
    _sha, nodes = ltm_nodes([dict(r, active=True) for r in ROWS])
    assert {n.id: n.title for n in nodes} == {"DA.ltm.18": ltm_title(ROWS[0]), "DA.ltm.4": ltm_title(ROWS[1])}
    # the trader's known-id set is parsed from the index text exactly like this
    index = "DA.directives.strategy.priced_kill — PRICED KILL\n" + "\n".join(lines)
    known = {line.split(" — ", 1)[0] for line in index.splitlines()}
    assert {"DA.ltm.18", "DA.ltm.4"} <= known


def test_ltm_ids_survive_validation_fold_and_repair():
    known = {"DA.directives.strategy.priced_kill", "DA.ltm.18", "DA.ltm.4"}
    assert C.normalize_ids(["⟨DA.ltm.18 · cited 7d/30d/90d: 1/2/5⟩", "da.LTM.4", "DA.ltm.99"], known) == ["DA.ltm.18", "DA.ltm.4"]
    ds = [{"action": "hold", "ticker": "IRDM", "reason": "fresh entry", "cited": ["DA.ltm.4"]},
          {"action": "sell", "ticker": "TSLA", "reason": "breach"}]
    assert C.fold_into_decisions(ds, known) == ["DA.ltm.4"]
    assert C.parse_cites(ds[0]["reason"]) == ["DA.ltm.4"]
    used = C.apply_citation_repairs(ds, {"TSLA": ["DA.ltm.18", "DA.directives.strategy.priced_kill"]}, known)
    assert used == ["DA.ltm.18", "DA.directives.strategy.priced_kill"] and ds[1]["cited_via"] == "repair"
    # considered rejections may cite memory rows too
    cons = [{"ticker": "CMG", "verdict": "reject", "cited": ["DA.ltm.18"]}]
    C.fold_considered(cons, known)
    assert C.considered_rejections(cons) == [("DA.ltm.18", "CMG")]


def test_cited_memory_row_marks_its_ltm_served_row():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trade_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, ticker TEXT, "
                          "sell_timestamp TIMESTAMP, gain_loss_percentage FLOAT, gain_loss_amount FLOAT, original_reason TEXT)"))
    C.ensure_hits_schema(engine)
    C.record_served(engine, "h", "DeciderAgent", 23, "r1", [Selected("DA.ltm.18", "ltm", ""), Selected("DA.ltm.4", "ltm", "")])
    C.record_cited(engine, "h", "DeciderAgent", 23, "r1",
                   [{"action": "hold", "ticker": "IRDM", "reason": "keep [cites: DA.ltm.4]"}],
                   considered=[{"ticker": "CMG", "verdict": "reject", "cited": ["DA.ltm.18"]}])
    m = C.hit_map(engine, "h")
    assert m["DA.ltm.4"]["cited_7d"] == 1 and m["DA.ltm.18"]["cited_7d"] == 1
    assert m["DA.ltm.4"]["served_90d"] == 1                     # the served row was marked, no 'unserved' row
    hc = C.hit_counts(engine, "h", "DA.ltm.18")
    assert hc["routes"] == {"ltm": 1}
    engine.dispose()
