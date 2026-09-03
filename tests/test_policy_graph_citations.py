"""Guideline citations: the reason suffix, id normalisation, folding the Decider's `cited` list, the
index the Decider is shown, and the health join over trade_decisions / trade_outcomes (SQLite)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from policy_graph import citations as C
from policy_graph.compile import read_version_dir

V21 = Path(__file__).resolve().parent.parent / "agents" / "decider" / "policy-graph" / "9ea09b9as" / "v21"


def test_append_parse_strip_roundtrip():
    r = C.append_cites("R1 pullback in uptrend K:310;D:2.8%", ["DA.directives.strategy.priced_kill", "da.soul.core_philosophy"])
    assert r == "R1 pullback in uptrend K:310;D:2.8% [cites: DA.directives.strategy.priced_kill, DA.soul.core_philosophy]"
    assert C.parse_cites(r) == ["DA.directives.strategy.priced_kill", "DA.soul.core_philosophy"]
    assert C.strip_cites(r) == "R1 pullback in uptrend K:310;D:2.8%"
    assert C.split_cites("plain reason") == ("plain reason", [])
    # replacing an existing suffix, never stacking two
    r2 = C.append_cites(r, ["DA.memory.lessons.regime"])
    assert r2.endswith("[cites: DA.memory.lessons.regime]") and r2.count("[cites:") == 1
    assert C.append_cites("x", []) == "x"
    assert C.parse_cites("no suffix [cites:]") == []


def test_normalize_ids_filters_and_caps():
    raw = ["DA.directives.strategy.priced_kill", "not an id", "DA.directives.strategy.priced_kill", "SA.root",
           "DA.Memory.Lessons.Regime", "junk.x", "DA.a", "DA.b", "DA.c", "DA.d", "DA.e"]
    out = C.normalize_ids(raw)
    assert out[:3] == ["DA.directives.strategy.priced_kill", "SA.root", "DA.memory.lessons.regime"]
    assert len(out) == C.MAX_CITES
    assert C.normalize_ids("DA.x, DA.y DA.z") == ["DA.x", "DA.y", "DA.z"]
    assert C.normalize_ids(["DA.x", "DA.y"], known={"DA.y"}) == ["DA.y"]
    assert C.normalize_ids(None) == []


def test_fold_into_decisions_moves_cited_into_reason():
    decisions = [
        {"action": "buy", "ticker": "AAA", "reason": "setup", "cited": ["DA.directives.strategy.priced_kill", "DA.nope"]},
        {"action": "hold", "ticker": "BBB", "reason": "keep", "cites": "DA.soul.core_philosophy"},
        {"action": "sell", "ticker": "CCC", "reason": "cut"},
        "not a dict",
    ]
    used = C.fold_into_decisions(decisions, known={"DA.directives.strategy.priced_kill", "DA.soul.core_philosophy"})
    assert used == ["DA.directives.strategy.priced_kill", "DA.soul.core_philosophy"]
    assert decisions[0]["reason"] == "setup [cites: DA.directives.strategy.priced_kill]" and "cited" not in decisions[0]
    assert decisions[1]["reason"] == "keep [cites: DA.soul.core_philosophy]" and "cites" not in decisions[1]
    assert decisions[2]["reason"] == "cut"


@pytest.mark.skipif(not (V21 / "manifest.json").exists(), reason="backfilled v21 not present")
def test_guideline_index_lists_rules_lessons_and_firing_code_blocks():
    v = read_version_dir(V21)
    ids = [i for i, _t in C.citable_nodes(v)]
    assert "DA.directives.strategy.priced_kill" in ids and "DA.memory.lessons.regime" in ids
    assert "DA.soul.core_philosophy" in ids
    assert "DA.root" not in ids and "DA.template.system" not in ids and "DA.directives" not in ids
    assert "DA.code.confirmation_policy" in ids and "DA.code.json_fallback" not in ids     # fires / does not fire
    assert ids.index("DA.code.confirmation_policy") > ids.index("DA.memory.lessons.regime")
    text_ = C.guideline_index(v)
    assert "DA.directives.strategy.priced_kill — PRICED KILL" in text_
    assert all(" — " in line for line in text_.splitlines())


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trade_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, run_id TEXT, "
                          "timestamp TIMESTAMP, data TEXT)"))
        conn.execute(text("CREATE TABLE trade_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, ticker TEXT, "
                          "sell_timestamp TIMESTAMP, gain_loss_percentage FLOAT, gain_loss_amount FLOAT, original_reason TEXT, "
                          "sell_reason TEXT)"))
        pk = "DA.directives.strategy.priced_kill"
        rows = [
            [{"action": "buy", "ticker": "AAA", "reason": f"r [cites: {pk}, DA.soul.core_philosophy]"},
             {"action": "hold", "ticker": "BBB", "reason": "plain"}],
            [{"action": "sell", "ticker": "AAA", "reason": f"breach [cites: {pk}]"}],
            {"decisions": [{"action": "buy", "ticker": "CCC", "reason": "no cite"}]},
        ]
        for k, data in enumerate(rows):
            conn.execute(text("INSERT INTO trade_decisions (config_hash, run_id, timestamp, data) VALUES ('h', :r, :t, :d)"),
                         {"r": f"run{k}", "t": datetime(2026, 9, 3, 10 + k), "d": json.dumps(data)})
        outcomes = [("AAA", 2.5, 12.0, f"r [cites: {pk}, DA.soul.core_philosophy]"),
                    ("DDD", -1.5, -8.0, f"x [cites: {pk}]"),
                    ("EEE", 4.0, 20.0, "no cite"),
                    ("SYNC", 9.0, 90.0, f"Schwab synced position [cites: {pk}]")]
        for k, (t, pct, amt, reason) in enumerate(outcomes):
            conn.execute(text("INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, "
                              "gain_loss_amount, original_reason) VALUES ('h', :tk, :ts, :p, :a, :r)"),
                         {"tk": t, "ts": datetime(2026, 9, 4, 10 + k), "p": pct, "a": amt, "r": reason})
    yield engine
    engine.dispose()


def test_citation_health_joins_decisions_and_closed_trades(db):
    h = C.citation_health(db, "h", "DA.directives.strategy.priced_kill")
    assert h["decisions"] == 2 and h["by_action"] == {"buy": 1, "sell": 1}
    assert h["closed"] == 2 and h["wins"] == 1 and h["losses"] == 1 and h["win_rate"] == 0.5
    assert h["pnl"] == 4.0 and h["avg_gain_pct"] == 0.5
    assert [r["ticker"] for r in h["recent_closed"]] == ["DDD", "AAA"]
    assert [r["ticker"] for r in h["recent_decisions"]] == ["AAA", "AAA"]
    soul = C.citation_health(db, "h", "DA.soul.core_philosophy")
    assert soul["decisions"] == 1 and soul["closed"] == 1 and soul["win_rate"] == 1.0
    none = C.citation_health(db, "h", "DA.memory.lessons.regime")
    assert none["decisions"] == 0 and none["closed"] == 0 and none["win_rate"] is None
