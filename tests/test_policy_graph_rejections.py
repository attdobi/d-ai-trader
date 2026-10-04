"""Citations on rejections: the Decider's top-level "considered" array carries `cited` on its reject /
watch elements. fold_considered validates them, record_cited logs them with action 'reject', and the
decision paths / hit counts / citation health count them as citations — never as trades (SQLite)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from policy_graph import citations as C
from policy_graph import paths as P
from policy_graph.assembly import Selected

PK, EX, RG, QU = ("DA.directives.strategy.priced_kill", "DA.directives.strategy.extension_cap",
                  "DA.memory.lessons.regime", "DA.directives.strategy.quarantine")
NOW = datetime(2026, 10, 2, 12)


# ----------------------------------------------------------------------------- folding
def test_fold_considered_validates_in_place_and_counts_rejections():
    considered = [
        {"ticker": "CMG", "verdict": "reject", "why": "extended", "cited": ["⟨DA.directives.strategy.extension_cap⟩", "DA.nope"]},
        {"ticker": "TGT", "verdict": "Watch", "why": "no setup yet", "cites": "DA.memory.lessons.regime"},
        {"ticker": "IRDM", "verdict": "reject", "why": "quarantined"},                       # uncited: accepted
        {"ticker": "XYZ", "verdict": "reject", "why": "junk ids", "cited": ["not an id"]},
        {"ticker": "NVDA", "verdict": "hold", "why": "thesis intact", "cited": [PK]},        # mirrors a decision
        "not a dict",
    ]
    counts = C.fold_considered(considered, known={EX, RG, PK})
    assert counts == {"items": 5, "rejections": 4, "cited": 2, "uncited": 2}
    assert considered[0]["cited"] == [EX]
    assert considered[1]["cited"] == [RG] and "cites" not in considered[1]
    assert "cited" not in considered[2] and "cited_dropped" not in considered[2]
    assert considered[3]["cited_raw"] == ["not an id"] and considered[3]["cited_dropped"] == "not valid guideline ids"
    assert considered[4]["cited"] == [PK]
    assert C.fold_considered(None) == {"items": 0, "rejections": 0, "cited": 0, "uncited": 0}
    # an id outside the served index is dropped, the raw value kept for the audit
    c = [{"ticker": "A", "verdict": "reject", "cited": ["DA.not.served"]}]
    C.fold_considered(c, known={EX})
    assert c[0]["cited_dropped"] == "not in the served index" and "cited" not in c[0]


def test_considered_rejections_only_reject_type_verdicts():
    considered = [{"ticker": "cmg", "verdict": "reject", "cited": [EX, PK]},
                  {"ticker": "TGT", "verdict": "watch", "cited": [RG]},
                  {"ticker": "NVDA", "verdict": "hold", "cited": [PK]},
                  {"ticker": "AMD", "verdict": "buy", "cited": [PK]},
                  {"ticker": "X", "verdict": "pass", "cited": "DA.directives.strategy.quarantine"},
                  {"ticker": "Y", "verdict": "reject"}]
    assert C.considered_rejections(considered) == [(EX, "CMG"), (PK, "CMG"), (RG, "TGT"), (QU, "X")]
    assert C.is_rejection({"verdict": " REJECT "}) and not C.is_rejection({"verdict": "sell"}) and not C.is_rejection("x")


# ----------------------------------------------------------------------------- hit log
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
    yield engine
    engine.dispose()


def _hits(engine, run_id):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT node_id, route, served, cited, ticker, action FROM policy_graph_hits "
                                 "WHERE run_id = :r ORDER BY id"), {"r": run_id}).fetchall()
    return [tuple(r) for r in rows]


def _cycle(engine, run_id, at, decisions, considered):
    C.record_served(engine, "h", "DeciderAgent", 23, run_id,
                    [Selected(PK, "core", "strategy_directives"), Selected(EX, "regime", "strategy_directives"),
                     Selected(RG, "regime", "memory")], decided_at=at)
    C.fold_considered(considered, known={PK, EX, RG, QU})
    n = C.record_cited(engine, "h", "DeciderAgent", 23, run_id, decisions, considered=considered, decided_at=at)
    data = list(decisions) + [{"kind": "considered_audit", "considered": considered}]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO trade_decisions (config_hash, run_id, timestamp, data) VALUES ('h', :r, :t, :d)"),
                     {"r": run_id, "t": at, "d": json.dumps(data)})
    return n


def test_record_cited_writes_reject_rows_without_relabelling_decisions(db):
    at = NOW - timedelta(days=1)
    decisions = [{"action": "buy", "ticker": "AAA", "reason": f"setup [cites: {PK}]"}]
    considered = [{"ticker": "CMG", "verdict": "reject", "why": "chase", "cited": [EX, PK]},
                  {"ticker": "TGT", "verdict": "reject", "why": "also extended", "cited": [EX]},    # same guideline: one row per run
                  {"ticker": "IRDM", "verdict": "watch", "why": "quarantine", "cited": [QU]},       # never served this cycle
                  {"ticker": "AAA", "verdict": "buy", "cited": [RG]}]                                # mirrors the decision: not logged
    n = _cycle(db, "r1", at, decisions, considered)
    assert n == 4
    rows = _hits(db, "r1")
    # the decision keeps its claim on the served row of PK; the rejection that also cited PK gets its own row
    assert (PK, "core", 1, 1, "AAA", "buy") in rows
    assert (PK, "core", 0, 1, "CMG", "reject") in rows
    # EX was served and only rejections cited it: the served row becomes the rejection (first ticker)
    assert (EX, "regime", 1, 1, "CMG", "reject") in rows
    assert sum(1 for r in rows if r[0] == EX) == 1
    # QU was never served: an 'unserved' rejection row, like an unserved decision citation
    assert (QU, "unserved", 0, 1, "IRDM", "reject") in rows
    # RG: served, cited by nothing that counts (the "buy" considered element mirrors a decision)
    assert (RG, "regime", 1, 0, None, None) in rows
    # idempotent per run: a second pass adds nothing
    assert C.record_cited(db, "h", "DeciderAgent", 23, "r1", [], considered=considered, decided_at=at) == 0
    assert len(_hits(db, "r1")) == len(rows)


def test_record_cited_without_considered_is_unchanged(db):
    at = NOW - timedelta(days=1)
    C.record_served(db, "h", "DeciderAgent", 23, "r0", [Selected(PK, "core", "strategy_directives")], decided_at=at)
    assert C.record_cited(db, "h", "DeciderAgent", 23, "r0", [{"action": "hold", "ticker": "B", "reason": f"x [cites: {PK}]"}],
                          decided_at=at) == 1
    assert _hits(db, "r0") == [(PK, "core", 1, 1, "B", "hold")]
    assert C.record_cited(db, "h", "DeciderAgent", 23, "r0", [], considered=[{"verdict": "reject"}]) == 0


def test_paths_show_a_reject_column_and_keep_rejections_out_of_win_rate(db):
    _cycle(db, "r1", NOW - timedelta(days=1),
           [{"action": "buy", "ticker": "AAA", "reason": f"setup [cites: {PK}]"}],
           [{"ticker": "CMG", "verdict": "reject", "why": "chase", "cited": [EX]}])
    _cycle(db, "r2", NOW - timedelta(days=2),
           [{"action": "sell", "ticker": "AAA", "reason": f"kill [cites: {PK}]"}],
           [{"ticker": "TGT", "verdict": "reject", "why": "chase", "cited": [EX, PK]}])
    with db.begin() as conn:
        conn.execute(text("INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, "
                          "original_reason) VALUES ('h', 'AAA', :t, -2.0, -10.0, :r)"),
                     {"t": NOW - timedelta(hours=20), "r": f"setup [cites: {PK}]"})
    rep = P.path_report(db, "h", days=30, now=NOW)
    f = rep["frequency"]
    assert "reject" in f["actions"] and {"buy", "sell"} <= set(f["actions"])
    assert {"source": EX, "target": "reject", "value": 2} in f["flows_out"]
    assert {"source": PK, "target": "reject", "value": 1} in f["flows_out"]
    assert {"source": "regime", "target": EX, "value": 2} in f["flows_in"]       # route from the served rows of the cycle
    # a guideline that only decided rejections is not "served but never cited" dead weight
    assert EX not in {d["id"] for d in f["served_never_cited"]}
    assert RG in {d["id"] for d in f["served_never_cited"]}
    # rejections are citations, never trades
    assert rep["decisions_cited"] == 2 and rep["rejections_cited"] == 2
    assert rep["closed_cited"] == 1 and rep["win_rate"] == 0.0
    q = {g["id"]: g for g in rep["quality"]}
    assert q[EX]["cited"] == 2 and q[EX]["closed"] == 0 and q[EX]["win_rate"] is None
    assert q[PK]["closed"] == 1 and q[PK]["wins"] == 0 and q[PK]["cited"] == 3


def test_hit_counts_and_citation_health_count_rejections_as_citations(db):
    _cycle(db, "r1", NOW - timedelta(days=1),
           [{"action": "hold", "ticker": "AAA", "reason": f"keep [cites: {PK}]"}],
           [{"ticker": "CMG", "verdict": "reject", "why": "chase", "cited": [EX]},
            {"ticker": "TGT", "verdict": "watch", "why": "wait", "cited": [EX]}])
    hc = C.hit_counts(db, "h", EX, now=NOW)
    assert hc["7d"]["cited"] == 1 and hc["7d"]["served"] == 1 and hc["7d"]["closed"] == 0
    assert hc["routes"] == {"regime": 1}
    hm = C.hit_map(db, "h", now=NOW)
    assert hm[EX]["cited_7d"] == 1
    h = C.citation_health(db, "h", EX)
    assert h["decisions"] == 0 and h["by_action"] == {} and h["closed"] == 0 and h["win_rate"] is None
    assert h["rejections"] == 2 and [r["ticker"] for r in h["recent_rejections"]] == ["CMG", "TGT"]
    hp = C.citation_health(db, "h", PK)
    assert hp["decisions"] == 1 and hp["by_action"] == {"hold": 1} and hp["rejections"] == 0
