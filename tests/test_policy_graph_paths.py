"""Decision paths: route → guideline → action flows, gaps (cited-unserved / served-never-cited),
and per-guideline quality with co-citations, over the hit log + outcomes + decisions (SQLite)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from policy_graph import citations as C
from policy_graph import paths as P
from policy_graph.assembly import Selected

PK, RG, EX = "DA.directives.strategy.priced_kill", "DA.memory.lessons.regime", "DA.directives.strategy.extension_cap"
NOW = datetime(2026, 10, 1, 12)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trade_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, ticker TEXT, "
                          "sell_timestamp TIMESTAMP, gain_loss_percentage FLOAT, gain_loss_amount FLOAT, original_reason TEXT, "
                          "sell_reason TEXT)"))
        conn.execute(text("CREATE TABLE trade_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, run_id TEXT, "
                          "timestamp TIMESTAMP, data TEXT)"))
    C.ensure_hits_schema(engine)
    served = [Selected(PK, "core", "strategy_directives"), Selected(RG, "regime", "memory"), Selected(EX, "core", "strategy_directives")]
    for k, (run, delta, decisions) in enumerate([
        ("r1", 1, [{"action": "buy", "ticker": "AAA", "reason": f"x [cites: {PK}, {RG}]"}]),
        ("r2", 3, [{"action": "buy", "ticker": "BBB", "reason": f"y [cites: {PK}]"}, {"action": "hold", "ticker": "AAA", "reason": f"z [cites: {RG}]"}]),
        ("r3", 5, [{"action": "sell", "ticker": "AAA", "reason": f"cut [cites: {PK}, DA.soul.core_philosophy]"}]),
    ]):
        at = NOW - timedelta(days=delta)
        C.record_served(engine, "h", "DeciderAgent", 23, run, served, decided_at=at)
        C.record_cited(engine, "h", "DeciderAgent", 23, run, decisions, decided_at=at)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO trade_decisions (config_hash, run_id, timestamp, data) VALUES ('h', :r, :t, :d)"),
                         {"r": run, "t": at, "d": json.dumps(decisions)})
    with engine.begin() as conn:
        for tk, pct_, amt, reason, delta in [("AAA", 2.0, 12.0, f"x [cites: {PK}, {RG}]", 1), ("BBB", -1.5, -9.0, f"y [cites: {PK}]", 1),
                                             ("OLD", 5.0, 50.0, f"old [cites: {PK}]", 200)]:
            conn.execute(text("INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, "
                              "original_reason) VALUES ('h', :tk, :t, :p, :a, :r)"),
                         {"tk": tk, "t": NOW - timedelta(days=delta), "p": pct_, "a": amt, "r": reason})
    yield engine
    engine.dispose()


def test_frequency_flows_and_gaps(db):
    rep = P.path_report(db, "h", days=90, now=NOW, titles={PK: "PRICED KILL", RG: "regime lesson"})
    assert not rep["empty"] and rep["runs"] == 3 and rep["decisions_cited"] == 4 and rep["closed_cited"] == 2
    f = rep["frequency"]
    assert [g["id"] for g in f["guidelines"]] == [PK, RG, "DA.soul.core_philosophy"]
    assert f["guidelines"][0] == {"id": PK, "title": "PRICED KILL", "cited": 3, "served": 3}
    assert {"source": "core", "target": PK, "value": 3} in f["flows_in"]
    assert {"source": "regime", "target": RG, "value": 2} in f["flows_in"]
    assert {"source": "unserved", "target": "DA.soul.core_philosophy", "value": 1} in f["flows_in"]
    assert {"source": PK, "target": "buy", "value": 2} in f["flows_out"] and {"source": PK, "target": "sell", "value": 1} in f["flows_out"]
    assert f["routes"] == ["core", "regime", "unserved"] and f["actions"] == ["buy", "hold", "sell"]
    assert [g["id"] for g in f["cited_unserved"]] == ["DA.soul.core_philosophy"]
    assert [g["id"] for g in f["served_never_cited"]] == [EX] and f["served_never_cited_total"] == 1


def test_quality_and_co_citations(db):
    rep = P.path_report(db, "h", days=90, now=NOW)
    q = {r["id"]: r for r in rep["quality"]}
    pk = q[PK]
    assert pk["closed"] == 2 and pk["wins"] == 1 and pk["losses"] == 1 and pk["win_rate"] == 0.5 and pk["pnl"] == 3.0
    assert pk["co_on_wins"] == [{"id": RG, "title": RG, "count": 1}] and pk["co_on_losses"] == []
    assert {c["id"] for c in pk["co_cited"]} == {RG, "DA.soul.core_philosophy"}
    rg = q[RG]
    assert rg["closed"] == 1 and rg["win_rate"] == 1.0 and rg["cited"] == 2
    assert rep["win_rate"] == 0.5
    # the 200-day-old outcome is outside the 90d window but inside 365d
    rep365 = P.path_report(db, "h", days=365, now=NOW)
    assert {r["id"]: r for r in rep365["quality"]}[PK]["closed"] == 3


def test_empty_window(db):
    rep = P.path_report(db, "h", days=30, now=NOW + timedelta(days=100))
    assert rep["empty"] and "No cited decisions" in rep["note"] and rep["quality"] == []
    assert P.path_report(db, "h", days=7, now=NOW)["days"] == 90        # unknown window falls back to 90
