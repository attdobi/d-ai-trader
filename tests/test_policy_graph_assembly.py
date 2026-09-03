"""Graph-driven assembly for the Decider: deterministic selection by context, regime-first rule
ordering, id + record tags, dropped ids listed, and the per-run hit log with window counts."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from policy_graph import assembly as A
from policy_graph import citations as C
from policy_graph import service
from policy_graph.compile import read_version_dir
from policy_graph.model import InheritedText

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_pg_service_tests_asm", HERE / "test_policy_graph_service.py")
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
CFG = _svc.CFG


@pytest.fixture
def version(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _svc.DDL:
            conn.execute(text(ddl))
        v, sd, soul, mem, by, active, at, rid = next(r for r in _svc.DECIDER_ROWS if r[0] == 21)
        conn.execute(text("""
            INSERT INTO prompt_versions (id, agent_type, version, system_prompt, user_prompt_template,
                strategy_directives, soul, memory, description, created_by, is_active, config_hash, created_at)
            VALUES (:id, 'DeciderAgent', 21, :sp, :up, :sd, :soul, :mem, 'v21', :by, 1, :h, :at)
        """), {"id": rid, "sp": _svc.SYS21, "up": _svc.USER21, "sd": sd, "soul": soul, "mem": mem, "by": by, "h": CFG, "at": at})
        for rid2, at2, kind, tags, ticker, content, source, weight, active2 in _svc.MEMORY_ROWS:
            conn.execute(text("""
                INSERT INTO decider_memory (id, config_hash, created_at, updated_at, kind, tags, ticker, content,
                    source, weight, active) VALUES (:id, :h, :at, :at, :k, :tags, :tk, :c, :s, :w, :active)
            """), {"id": rid2, "h": CFG, "at": at2, "k": kind, "tags": tags, "tk": ticker, "c": content, "s": source,
                   "w": weight, "active": active2})
    monkeypatch.setattr(service.inherited, "resolve_inherited",
                        lambda *a, **k: InheritedText(text="", source_path="x", git_sha=None, resolution="worktree"))
    service.ensure_materialized(engine, CFG, "DeciderAgent", 21, repo_root=tmp_path, is_margin_account=False)
    v = read_version_dir(tmp_path / "agents" / "decider" / "policy-graph" / CFG / "v21")
    engine.dispose()
    return v


def test_core_rules_always_served_and_regime_rules_first(version):
    ctx = A.Context(regime="RISK-OFF", holdings=[], watchlist=[], quarantined=[])
    out = A.assemble(version, ctx)
    ids = [s.node_id for s in out.served]
    rules = [i for i in ids if i.startswith("DA.directives.strategy.") and version.nodes[i].node_type == "rule"]
    assert set(rules) == {i for i in version.nodes if i.startswith("DA.directives.strategy.") and version.nodes[i].node_type == "rule"}
    assert "risk-off" in version.nodes[rules[0]].body.lower()          # regime-matching rule moved to the front
    assert "DA.directives.ground_truth" in ids and "DA.soul.mission" in ids
    routes = {s.node_id: s.route for s in out.served}
    assert routes["DA.directives.ground_truth"] == "core" and routes["DA.soul.mission"] == "identity"
    assert "PRICED KILL" in out.strategy_directives and "⟨DA.directives.strategy.priced_kill⟩" in out.strategy_directives


def test_ticker_and_recency_routes_and_dropped_list(version):
    old_entries = [i for i in version.nodes if i.startswith("DA.memory.log.2026_06")]
    assert old_entries
    ctx = A.Context(regime="RISK-ON", holdings=["IRDM"], watchlist=[], quarantined=[], today=datetime(2026, 9, 3))
    out = A.assemble(version, ctx)
    routes = {s.node_id: s.route for s in out.served}
    irdm = [i for i in version.nodes if "irdm" in i]
    assert irdm and routes[irdm[0]] == "ticker"                   # kept only because IRDM is held
    ctx2 = A.Context(regime="RISK-ON", holdings=[], watchlist=[], quarantined=[], today=datetime(2026, 9, 3))
    out2 = A.assemble(version, ctx2)
    assert irdm[0] in out2.dropped and "Not shown this cycle" in out2.memory and irdm[0] in out2.memory
    recent = [i for i in version.nodes if i.startswith("DA.memory.log.2026_09")]
    assert all(i not in out2.dropped for i in recent)              # within RECENT_DAYS of `today`
    ctx3 = A.Context(regime="", today=datetime(2027, 1, 1))
    out3 = A.assemble(version, ctx3)
    assert all(i in out3.dropped for i in recent)


def test_quarantine_route(version):
    quar = [i for i in version.nodes if "quarantine" in i and version.nodes[i].node_type == "lesson"]
    assert quar
    out = A.assemble(version, A.Context(regime="", quarantined=["SMCI"], today=datetime(2026, 12, 1)))
    routes = {s.node_id: s.route for s in out.served}
    assert routes[quar[0]] == "quarantine"


def test_health_tag_rendering(version):
    pk = "DA.directives.strategy.priced_kill"
    health = {pk: {"7d": {"cited": 3}, "30d": {"cited": 12}, "90d": {"cited": 20, "closed": 12, "wins": 7, "win_rate": 7 / 12}}}
    out = A.assemble(version, A.Context(regime="MIXED"), health=health)
    assert f"⟨{pk} · cited 7d/30d/90d: 3/12/20 · win 58% n=12⟩" in out.strategy_directives
    assert out.health_used
    assert A.health_tag("DA.x", {}) == " ⟨DA.x⟩"


# ----------------------------------------------------------------------------- hit log
@pytest.fixture
def hits_db():
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


def test_served_cited_windows_and_routes(hits_db):
    pk, rg = "DA.directives.strategy.priced_kill", "DA.memory.lessons.regime"
    now = datetime(2026, 9, 10, 12)
    served = [A.Selected(pk, "core", "strategy_directives"), A.Selected(rg, "regime", "memory")]
    assert C.record_served(hits_db, "h", "DeciderAgent", 23, "run1", served, decided_at=now - timedelta(days=2)) == 2
    assert C.record_served(hits_db, "h", "DeciderAgent", 23, "run2", served, decided_at=now - timedelta(days=40)) == 2
    decisions = [{"action": "buy", "ticker": "AAA", "reason": f"x [cites: {pk}]"},
                 {"action": "hold", "ticker": "BBB", "reason": f"y [cites: {pk}, DA.soul.core_philosophy]"}]
    assert C.record_cited(hits_db, "h", "DeciderAgent", 23, "run1", decisions, decided_at=now - timedelta(days=2)) == 3
    with hits_db.begin() as conn:
        conn.execute(text("INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, "
                          "original_reason) VALUES ('h', 'AAA', :t, 2.0, 10, :r)"), {"t": now - timedelta(days=1), "r": f"x [cites: {pk}]"})
    h = C.hit_counts(hits_db, "h", pk, now=now)
    assert h["7d"]["cited"] == 1 and h["7d"]["served"] == 1 and h["90d"]["served"] == 2 and h["1y"]["cited"] == 1
    assert h["7d"]["closed"] == 1 and h["7d"]["wins"] == 1 and h["7d"]["win_rate"] == 1.0
    assert h["routes"] == {"core": 1}
    soul = C.hit_counts(hits_db, "h", "DA.soul.core_philosophy", now=now)
    assert soul["7d"]["cited"] == 1 and soul["7d"]["served"] == 0 and soul["routes"] == {"unserved": 1}
    m = C.hit_map(hits_db, "h", now=now)
    assert m[pk] == {"cited_7d": 1, "cited_30d": 1, "cited_90d": 1, "cited_1y": 1, "served_90d": 2}
    assert m[rg]["cited_90d"] == 0 and m[rg]["served_90d"] == 2
    hp = C.health_for_prompt(hits_db, "h", [pk, rg, "DA.zzz"], now=now)
    assert hp[pk]["7d"]["cited"] == 1 and hp[pk]["90d"]["closed"] == 1 and "DA.zzz" not in hp
    assert rg in hp and hp[rg]["30d"]["cited"] == 0


def test_backfill_hits_from_decisions(hits_db):
    pk = "DA.directives.strategy.priced_kill"
    with hits_db.begin() as conn:
        conn.execute(text("INSERT INTO trade_decisions (config_hash, run_id, timestamp, data) VALUES ('h', 'r9', :t, :d)"),
                     {"t": datetime(2026, 9, 3, 10), "d": f'[{{"action": "buy", "ticker": "AAA", "reason": "x [cites: {pk}]"}}]'})
    assert C.backfill_hits_from_decisions(hits_db, "h") == 1
    assert C.backfill_hits_from_decisions(hits_db, "h") == 0
    h = C.hit_counts(hits_db, "h", pk, now=datetime(2026, 9, 4))
    assert h["7d"]["cited"] == 1 and h["routes"] == {"unserved": 1}


def test_news_entities_trend_and_tag_routes(version):
    irdm = next(i for i in version.nodes if "irdm" in i)
    far = datetime(2026, 12, 1)
    routes = lambda ctx: {s.node_id: s.route for s in A.assemble(version, ctx).served}
    assert routes(A.Context(news=["IRDM"], today=far))[irdm] == "news"
    assert routes(A.Context(entities=["irdm"], today=far))[irdm] == "entities"
    assert routes(A.Context(trend=["IRDM"], today=far))[irdm] == "trend"
    assert routes(A.Context(holdings=["IRDM"], news=["IRDM"], today=far))[irdm] == "ticker"     # holdings win
    # tag hop: an entry sharing a #tag with a contextually served entry comes along
    tagged = [i for i in version.nodes if version.nodes[i].node_type == "entry" and A._plain_tags(version.nodes[i])]
    assert tagged
    src = tagged[0]
    tag = sorted(A._plain_tags(version.nodes[src]))[0]
    partner = next((i for i in tagged if i != src and tag in A._plain_tags(version.nodes[i])), None)
    ctx = A.Context(regime="", today=far)
    base = A.assemble(version, ctx)
    assert src in base.dropped
    if partner:
        # serve `src` via a ticker in its body, then its tag partner should ride along
        tk = sorted(A._node_tickers(version.nodes[src]))
        if tk:
            out = A.assemble(version, A.Context(holdings=[tk[0]], today=far))
            r = {s.node_id: s.route for s in out.served}
            assert r[src] == "ticker" and r.get(partner) == "tag"


def test_assembled_sizes_and_context_summary(version):
    out = A.assemble(version, A.Context(regime="MIXED", holdings=["X"], news=["A", "B"]))
    assert out.chars_full > 0 and out.chars_served > 0
    assert out.routes["core"] >= 8 and out.routes.get("identity")
    assert A.Context(regime="MIXED", holdings=["X"], news=["A", "B"]).summary() == {
        "regime": "MIXED", "holdings": 1, "watchlist": 0, "quarantined": 0, "news": 2, "entities": 0, "trend": 0}


def test_run_log_and_stats(hits_db):
    now = datetime(2026, 9, 10, 12)
    C.record_run(hits_db, "h", "DeciderAgent", 23, "run1", served=30, dropped=4, chars_full=16000, chars_served=14800,
                 routes={"core": 14, "news": 2}, context={"regime": "RISK-OFF"}, decided_at=now)
    C.record_run(hits_db, "h", "DeciderAgent", 23, "run2", served=28, dropped=6, chars_full=16000, chars_served=13200,
                 routes={"core": 14, "trend": 1}, context={"regime": "MIXED"}, decided_at=now + timedelta(hours=2))
    st = C.run_stats(hits_db, "h", "DeciderAgent")
    assert st["runs"] == 2 and st["latest"]["run_id"] == "run2" and st["latest"]["served"] == 28
    assert abs(st["latest"]["ratio"] - 0.825) < 1e-9 and abs(st["average"]["ratio"] - 0.875) < 1e-9
    assert st["routes"] == {"core": 28, "news": 2, "trend": 1} and st["latest"]["context"] == {"regime": "MIXED"}
    assert C.run_stats(hits_db, "h", "SummarizerAgent") is None
