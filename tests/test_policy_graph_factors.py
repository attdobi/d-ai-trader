"""World events & market factors (Phase 4): factors per cycle from the run log + the event calendar +
snapshots, the report (flows, per-factor decisions and closed trades), the read-time nodes/edges, and
the details payload. SQLite, no network, no config."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

import event_calendar as ec
from policy_graph import citations as C
from policy_graph import factors as F
from policy_graph.assembly import Selected
from policy_graph.model import Node

RG = "DA.directives.strategy.regime_gate"
EG = "DA.directives.strategy.event_gate"
LR = "DA.memory.lessons.regime"
LE = "DA.memory.lessons.event_risk"
CI = "DA.code.index_regime"
NOW = datetime(2026, 9, 17, 10, 0)


def _node(nid, node_type, body="", owner="db", tickers=None, field="strategy_directives"):
    return Node(id=nid, agent="DeciderAgent", title=nid.split(".")[-1].upper(), node_type=node_type,
                parent=".".join(nid.split(".")[:-1]), field=field, body=body, owner=owner,
                tickers=list(tickers or []))


VERSION_NODES = {n.id: n for n in [
    _node("DA.root", "root"), _node("DA.directives.strategy", "section"),
    _node(RG, "rule", "1. REGIME GATE — RISK-OFF = cash default."),
    _node(EG, "rule", "9. EVENT GATE — read the EVENT CALENDAR block."),
    _node(LR, "lesson", "- **#regime** In RISK-OFF cash is the default.", field="memory"),
    _node(LE, "lesson", "- **#event-risk** paid for by [[MDB]]", field="memory", tickers=["MDB"]),
    _node(CI, "code", "# DEPLOYMENT RULE BY REGIME", owner="code", field=None),
    _node("DA.memory.log.2026_09_02_regime", "entry", "## 2026-09-02 #regime\n- RISK-OFF cost us.", field="memory"),
    _node("DA.ticker.tsla", "ticker", "", owner="generated", tickers=["TSLA"], field=None),
]}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trade_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, ticker TEXT, "
                          "sell_timestamp TIMESTAMP, gain_loss_percentage FLOAT, gain_loss_amount FLOAT, original_reason TEXT)"))
    C.ensure_hits_schema(engine)
    C.ensure_runs_schema(engine)
    ec.ensure_tables(engine)
    served = [Selected(RG, "core", "strategy_directives"), Selected(EG, "core", "strategy_directives")]
    runs = [
        # r1: Mon Sep 14, RISK-OFF, FOMC in 2 sessions (window) — buys TSLA citing the event gate
        ("r1", datetime(2026, 9, 14, 10, 0), "RISK-OFF", [{"action": "buy", "ticker": "TSLA", "reason": f"x [cites: {EG}, {RG}]"}]),
        # r2: Tue Sep 15, RISK-OFF, FOMC in 1 session — holds TSLA citing the regime gate
        ("r2", datetime(2026, 9, 15, 10, 0), "RISK-OFF", [{"action": "hold", "ticker": "TSLA", "reason": f"y [cites: {RG}]"}]),
        # r3: Thu Sep 10, RISK-OFF, CPI next session — cash
        ("r3", datetime(2026, 9, 10, 10, 0), "RISK-OFF", [{"action": "hold", "ticker": "CASH", "reason": f"z [cites: {RG}]"}]),
        # r4: Tue Sep 1, RISK-ON, quiet — buy AAA citing the regime gate
        ("r4", datetime(2026, 9, 1, 10, 0), "RISK-ON", [{"action": "buy", "ticker": "AAA", "reason": f"w [cites: {RG}]"}]),
        # r5: no regime in context (unreadable) — nothing
        ("r5", datetime(2026, 9, 2, 10, 0), None, []),
    ]
    for run, at, regime, decisions in runs:
        C.record_served(engine, "h", "DeciderAgent", 28, run, served, decided_at=at)
        C.record_cited(engine, "h", "DeciderAgent", 28, run, decisions, decided_at=at)
        C.record_run(engine, "h", "DeciderAgent", 28, run, served=2, dropped=0, chars_full=10, chars_served=10,
                     routes={"core": 2}, context=({"regime": regime} if regime else {}), decided_at=at)
    # snapshot only for r2 (as if the trader was restarted then): TSLA reports within 2 sessions
    ctx = {"today": "2026-09-15", "regime": "RISK-OFF", "risk_score": 90, "risk_level": "EXTREME", "macro_window": True,
           "macro_reason": "FOMC decision Wed 2026-09-16 (in 1 session)", "macro": {"fomc": {"next": "2026-09-16", "sessions_to": 1}},
           "holdings_earnings": [{"ticker": "TSLA", "date": "2026-09-17", "sessions_to": 2, "flag": "reports_within_2"}],
           "watchlist_earnings": [{"ticker": "MRK", "date": "2026-10-29", "sessions_to": 30, "flag": None}],
           "allowance": {}, "block": "# EVENT CALENDAR"}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO event_risk_snapshots (config_hash, run_id, as_of, session_date, regime, risk_score, risk_level,
            macro_window, macro_reason, holdings_earnings, watchlist_earnings, allowance, block)
            VALUES ('h', 'r2', '2026-09-15 10:00:00', '2026-09-15', 'RISK-OFF', 90, 'EXTREME', 1, :mr, :he, :we, '{}', '')"""),
                     {"mr": ctx["macro_reason"], "he": json.dumps(ctx["holdings_earnings"]), "we": json.dumps(ctx["watchlist_earnings"])})
        # TSLA bought on r1 (Sep 14), sold Sep 16 at a loss; AAA bought r4 (Sep 1), sold Sep 3 at a gain; OLD outside window
        for tk, at, pct_, amt, reason in [("TSLA", datetime(2026, 9, 16, 11, 0), -2.0, -8.0, f"x [cites: {EG}, {RG}]"),
                                          ("AAA", datetime(2026, 9, 3, 11, 0), 3.0, 12.0, f"w [cites: {RG}]"),
                                          ("OLD", datetime(2026, 5, 1, 11, 0), 5.0, 50.0, f"o [cites: {RG}]")]:
            conn.execute(text("INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, "
                              "original_reason) VALUES ('h', :tk, :t, :p, :a, :r)"), {"tk": tk, "t": at, "p": pct_, "a": amt, "r": reason})
    yield engine
    engine.dispose()


def test_run_factors_per_cycle():
    f = {x["key"]: x for x in F.run_factors(datetime(2026, 9, 14, 10, 0), "risk-off")}
    assert "regime.risk_off" in f and f["fomc.2026_09_16"]["phase"] == "window"
    assert "cpi.2026_09_11" not in f                                            # 1 session ago, not "printed today"
    f = {x["key"]: x for x in F.run_factors(datetime(2026, 9, 10, 10, 0), None, {"regime": "MIXED"})}
    assert "regime.mixed" in f and f["cpi.2026_09_11"]["phase"] == "window"
    f = {x["key"]: x for x in F.run_factors(datetime(2026, 9, 11, 10, 0), "RISK-ON")}
    assert f["cpi.2026_09_11"]["phase"] == "printed"
    snap = {"holdings_earnings": [{"ticker": "tsla", "date": "2026-09-17", "flag": "reports_within_2"}],
            "watchlist_earnings": [{"ticker": "MRK", "date": "2026-10-29", "flag": None}]}
    f = {x["key"]: x for x in F.run_factors(datetime(2026, 9, 23, 10, 0), "RISK-ON", snap)}
    assert f["earnings.tsla.2026_09_17"]["held"] and f["earnings.tsla.2026_09_17"]["ticker"] == "TSLA"
    assert not any(k.startswith("earnings.mrk") for k in f)
    assert F.run_factors(datetime(2026, 9, 23, 10, 0), "UNKNOWN") == []


def test_factor_report_flows_and_quality(db):
    rep = F.factor_report(db, "h", days=90, now=NOW, titles={EG: "EVENT GATE", RG: "REGIME GATE"})
    assert rep["runs"] == 5 and rep["runs_with_snapshot"] == 1 and not rep["empty"]
    by = {f["key"]: f for f in rep["factors"]}
    assert set(by) == {"regime.risk_off", "regime.risk_on", "fomc.2026_09_16", "cpi.2026_09_11", "earnings.tsla.2026_09_17"}
    assert [f["kind"] for f in rep["factors"]] == ["regime", "regime", "fomc", "cpi", "earnings"]
    off = by["regime.risk_off"]
    assert off["cycles"] == 3 and off["decisions"] == 3 and off["actions"] == {"buy": 1, "hold": 2}
    assert off["first"].startswith("2026-09-10") and off["last"].startswith("2026-09-15")
    fomc = by["fomc.2026_09_16"]
    assert fomc["cycles"] == 2 and fomc["decisions"] == 2 and fomc["tickers"] == ["TSLA"]
    assert [(g["id"], g["count"]) for g in fomc["guidelines"]] == [(RG, 2), (EG, 1)]
    assert {"source": "fomc.2026_09_16", "target": EG, "value": 1} in rep["flows_in"]
    assert {"source": EG, "target": "buy", "value": 1} in rep["flows_out"]
    # closed trades: TSLA entered on r1 (FOMC window, RISK-OFF) lost; AAA entered on r4 (RISK-ON) won; OLD outside window
    assert fomc["closed"] == 1 and fomc["losses"] == 1 and fomc["pnl"] == -8.0 and fomc["recent"][0]["ticker"] == "TSLA"
    assert fomc["recent"][0]["gain_pct"] == -200.0       # trade_outcomes stores a fraction; the panel shows percent
    assert off["closed"] == 1 and by["regime.risk_on"]["closed"] == 1 and by["regime.risk_on"]["win_rate"] == 1.0
    earn = by["earnings.tsla.2026_09_17"]
    assert earn["cycles"] == 1 and earn["held"] and earn["flag"] == "reports_within_2" and earn["closed"] == 0
    assert by["cpi.2026_09_11"]["actions"] == {"hold": 1}
    assert rep["guidelines"][0]["id"] == RG and rep["guidelines"][0]["title"] == "REGIME GATE"


def test_factor_nodes_and_edges(db):
    rep = F.factor_report(db, "h", days=90, now=NOW)
    nodes, edges = F.factor_nodes(rep, VERSION_NODES)
    ids = [n.id for n in nodes]
    assert ids[0] == "DA.factor" and "DA.factor.fomc.2026_09_16" in ids and "DA.factor.earnings.tsla.2026_09_17" in ids
    for n in nodes:
        assert n.owner == "world" and n.node_type == "factor" and n.locked and n.compiled == "never"
        assert n.parent == ("DA.root" if n.id == "DA.factor" else "DA.factor")
    assert all(e.edge_type == "triggers" and e.target in VERSION_NODES for e in edges)
    keys = {(e.source, e.target, e.provenance) for e in edges}
    assert ("DA.factor.fomc.2026_09_16", EG, "authored:factor_map") in keys
    assert ("DA.factor.fomc.2026_09_16", LE, "authored:factor_map") in keys
    assert ("DA.factor.regime.risk_off", RG, "authored:factor_map") in keys
    assert ("DA.factor.regime.risk_off", CI, "authored:factor_map") in keys
    assert ("DA.factor.regime.risk_off", LR, "authored:factor_map") in keys          # authored wins over the word match
    assert ("DA.factor.regime.risk_off", "DA.memory.log.2026_09_02_regime", "derived:regime_word") in keys
    assert ("DA.factor.earnings.tsla.2026_09_17", "DA.ticker.tsla", "derived:ticker") not in keys   # generated nodes skipped
    fomc_edges = {e.target: e for e in edges if e.source == "DA.factor.fomc.2026_09_16"}
    assert fomc_edges[RG].provenance == "derived:cited" and fomc_edges[RG].via == "cited 2×" and fomc_edges[RG].confidence == round(2 / 3, 3)
    assert fomc_edges[EG].provenance == "authored:factor_map" and fomc_edges[EG].via == "cited 1×"   # authored edge learns the count
    assert not any(e.provenance == "derived:cited" and e.confidence is None for e in edges)
    body = next(n for n in nodes if n.id == "DA.factor.fomc.2026_09_16").body
    assert "FOMC decision 2026-09-16" in body and "Closed trades entered under it: 1 (0W/1L)" in body and "rebuilt on every read" in body
    assert next(n for n in nodes if n.id.startswith("DA.factor.earnings")).tickers == ["TSLA"]


def test_factor_payload_and_empty_window(db):
    rep = F.factor_report(db, "h", days=90, now=NOW)
    p = F.factor_payload_for_node(rep, "DA.factor.fomc.2026_09_16")
    assert p["node_kind"] == "factor" and p["kind"] == "fomc" and p["cycles"] == 2 and p["decisions"] == 2
    g = F.factor_payload_for_node(rep, "DA.factor")
    assert g["node_kind"] == "group" and g["count"] == 5 and g["cycles"] == 5
    assert F.factor_payload_for_node(rep, "DA.factor.nope") is None
    empty = F.factor_report(db, "h", days=3, now=NOW + timedelta(days=200))
    assert empty["empty"] and empty["note"] and F.factor_nodes(empty, VERSION_NODES) == ([], [])
    missing = F.factor_report(create_engine("sqlite://"), "h", days=90, now=NOW)    # no tables at all
    assert missing["empty"] and missing["runs"] == 0
