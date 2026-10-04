"""policy_router labels / dataset / train on an in-memory world: a materialized policy version (the v21
fixture), logged cycles over three weeks, decisions whose reasons echo some guidelines, and a fake embeddings
endpoint. Covers the label definition (explicit / similar / ticker, marginal variant, considered citations),
decider_inputs feature detection, the time-split + leave-one-week-out protocol, the artifact and the reports,
and the CLI (sqlite URL, fake transport)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from policy_graph import service
from policy_graph.citations import ensure_hits_schema, ensure_runs_schema
from policy_graph.compile import read_version_dir
from policy_graph.model import InheritedText
from policy_router import train as T
from policy_router.dataset import decider_inputs_for, load_cycles
from policy_router.embed import EmbeddingClient
from policy_router.labels import label_node, parse_decisions, theta_from_pairs

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_pg_service_tests_router", HERE / "test_policy_graph_service.py")
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
_fspec = importlib.util.spec_from_file_location("policy_router_fakes", HERE / "policy_router_fakes.py")
fakes = importlib.util.module_from_spec(_fspec)
_fspec.loader.exec_module(fakes)
CFG = _svc.CFG

EXTRA_DDL = [
    "CREATE TABLE trade_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, timestamp TIMESTAMP, data TEXT, config_hash TEXT)",
    "CREATE TABLE summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, timestamp TIMESTAMP, run_id TEXT, data TEXT, config_hash TEXT)",
    "CREATE TABLE momentum_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, generated_at TIMESTAMP, "
    "companies_json TEXT, momentum_data TEXT, momentum_summary TEXT, momentum_recap TEXT, run_id TEXT)",
    "CREATE TABLE event_risk_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT, run_id TEXT, as_of TIMESTAMP, "
    "session_date DATE, regime TEXT, risk_score INTEGER, risk_level TEXT, macro_window BOOLEAN, macro_reason TEXT, "
    "fomc_date DATE, fomc_sessions INTEGER, cpi_date DATE, cpi_sessions INTEGER, jobs_date DATE, jobs_sessions INTEGER, "
    "holdings_earnings TEXT, watchlist_earnings TEXT, allowance TEXT, block TEXT)",
]


# ----------------------------------------------------------------------------- labels (pure)
def test_parse_decisions_reads_reasons_cites_considered_and_tickers():
    payload = [
        {"action": "hold", "ticker": "QCOM", "reason": "QCOM above kill. [cites: DA.directives.strategy.priced_kill]"},
        {"action": "hold", "ticker": "CASH", "reason": "no buy clears D<=1.3%", "cited": ["DA.ltm.31"]},
        {"kind": "considered_audit", "considered": [
            {"ticker": "ISRG", "verdict": "reject", "why": "K distance 1.33% exceeds the gate", "cited": ["DA.directives.strategy.priced_kill"]},
            {"ticker": "NET", "verdict": "reject", "why": "extended [cites: DA.directives.strategy.extension_cap]"},
            {"ticker": "ZS", "verdict": "watch", "why": "no catalyst"}]},
    ]
    out = parse_decisions([json.dumps(payload)])
    assert out["cited"] == {"DA.directives.strategy.priced_kill", "DA.ltm.31", "DA.directives.strategy.extension_cap"}
    assert out["tickers"] == {"QCOM", "ISRG", "NET", "ZS"} and out["holdings"] == {"QCOM"}
    assert "QCOM above kill." in out["reasons"] and "extended" in out["reasons"]
    assert out["considered_cites"] == 2 and len(out["pairs"]) == 4


def test_label_node_explicit_similar_ticker_and_marginal():
    n = fakes.node("DA.ltm.7", "ltm", "x", tickers=["IRDM"])
    R = np.array([[1.0, 0.0], [0.0, 1.0]])
    v = np.array([0.8, 0.6])
    assert label_node(n, cited={"DA.ltm.7"}, node_vec=v, reason_vecs=R, theta=0.99, decided_tickers=set())[:2] == (True, "explicit")
    assert label_node(n, cited=set(), node_vec=v, reason_vecs=R, theta=0.7, decided_tickers=set())[:2] == (True, "similar")
    assert label_node(n, cited=set(), node_vec=v, reason_vecs=R, theta=0.9, decided_tickers={"IRDM"})[:2] == (True, "ticker")
    assert label_node(n, cited=set(), node_vec=v, reason_vecs=R, theta=0.9, decided_tickers=set())[0] is False
    # marginal: reason 0 is explained better (0.95) by a pinned gate than by the node (0.8)
    assert label_node(n, cited=set(), node_vec=v, reason_vecs=R, theta=0.7, decided_tickers=set(),
                      pinned_best=np.array([0.95, 0.95]))[0] is False
    assert label_node(n, cited=set(), node_vec=v, reason_vecs=R, theta=0.7, decided_tickers=set(),
                      pinned_best=np.array([0.95, 0.95]), delta=0.2)[1] == "similar"
    assert theta_from_pairs([0.6, 0.7, 0.8], 0.5) == pytest.approx(0.7)
    assert theta_from_pairs([], 0.5, default=0.66) == 0.66


# ----------------------------------------------------------------------------- the logged world
@pytest.fixture
def world(tmp_path, monkeypatch):
    db_path = tmp_path / "world.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for ddl in list(_svc.DDL) + EXTRA_DDL:
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
        conn.execute(text("""INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, original_reason, created_at)
                             VALUES (:h, 'IONQ', '2026-09-07 10:00:00', 'x', '2026-09-07 10:00:00')"""), {"h": CFG})
    monkeypatch.setattr(service.inherited, "resolve_inherited",
                        lambda *a, **k: InheritedText(text="", source_path="x", git_sha=None, resolution="worktree"))
    service.ensure_materialized(engine, CFG, "DeciderAgent", 21, repo_root=tmp_path, is_margin_account=False)
    store = tmp_path / "agents" / "decider" / "policy-graph" / CFG
    version = read_version_dir(store / "v21")
    ensure_hits_schema(engine)
    ensure_runs_schema(engine)
    priced = version.nodes["DA.memory.lessons.priced_kill"].body
    regime_entry = version.nodes["DA.memory.log.2026_09_02_regime"].body
    rule_ids = [i for i, n in version.nodes.items() if n.node_type == "rule"]
    cited_rule = rule_ids[0]
    rule_body = version.nodes[cited_rule].body
    runs = []
    start = datetime(2026, 9, 7, 9, 0)                    # Monday; three ISO weeks of 6 cycles
    for i in range(18):
        at = start + timedelta(days=7 * (i // 6) + (i % 6) // 2, hours=2 * (i % 2))
        run_id = at.strftime("%Y%m%dT%H%M%S")
        runs.append(run_id)
        regime_cycle = i % 3 == 0
        reasons = [{"action": "hold", "ticker": "IONQ" if regime_cycle else "QCOM",
                    "reason": f"{rule_body[:160]} [cites: {cited_rule}]"},
                   {"action": "hold", "ticker": "CASH", "reason": (regime_entry if regime_cycle else priced[:200])}]
        considered = {"kind": "considered_audit", "considered": [{"ticker": "NET", "verdict": "reject", "why": "zebra giraffe"}]}
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO policy_graph_runs (config_hash, agent_type, prompt_version, run_id, decided_at,
                                 served, dropped, chars_full, chars_served, routes, context)
                                 VALUES (:h, 'DeciderAgent', 21, :r, :t, 1, 0, 1, 1, '{}', :ctx)"""),
                         {"h": CFG, "r": run_id, "t": at, "ctx": json.dumps({"regime": "RISK-OFF" if regime_cycle else "RISK-ON"})})
            for nid in ("DA.memory.log.2026_09_02_regime", "DA.memory.log.2026_09_01_kill_geometry", cited_rule):
                conn.execute(text("""INSERT INTO policy_graph_hits (config_hash, agent_type, prompt_version, run_id, decided_at,
                                     node_id, route, served, cited) VALUES (:h, 'DeciderAgent', 21, :r, :t, :n, 'recent', :s, :c)"""),
                             {"h": CFG, "r": run_id, "t": at, "n": nid, "s": True, "c": nid == cited_rule})
            conn.execute(text("INSERT INTO trade_decisions (run_id, timestamp, data, config_hash) VALUES (:r, :t, :d, :h)"),
                         {"r": run_id, "t": at, "d": json.dumps(reasons + [considered]), "h": CFG})
            conn.execute(text("INSERT INTO summaries (agent, timestamp, run_id, data, config_hash) VALUES ('A', :t, :r, :d, :h)"),
                         {"t": at, "r": run_id, "h": CFG, "d": json.dumps({"agent": "A", "summary": {
                             "headlines": ["[MU] Micron misses" if regime_cycle else "[NVDA] Nvidia rallies"],
                             "insights": "Risk-off tape; Watchlist: MU" if regime_cycle else "Risk-on; Watchlist: NVDA"}})})
            conn.execute(text("INSERT INTO momentum_snapshots (config_hash, run_id, companies_json, momentum_data) VALUES (:h, :r, :c, :m)"),
                         {"h": CFG, "r": run_id, "c": json.dumps([{"symbol": "NVDA"}]), "m": json.dumps([{"symbol": "MRVL"}])})
            if i % 2 == 0:
                conn.execute(text("""INSERT INTO event_risk_snapshots (config_hash, run_id, as_of, session_date, risk_score,
                                     holdings_earnings, watchlist_earnings, block) VALUES (:h, :r, :t, :d, 10, :he, :we, :b)"""),
                             {"h": CFG, "r": run_id, "t": at, "d": at.date(), "he": json.dumps([{"ticker": "QCOM"}]),
                              "we": json.dumps([{"ticker": "ISRG"}, {"ticker": "NET"}]), "b": "# EVENT CALENDAR FOMC soon"})
    return {"engine": engine, "store": store, "root": tmp_path, "runs": runs, "db_path": db_path, "cited_rule": cited_rule}


def test_load_cycles_reconstructs_context_labels_inputs_and_today(world):
    cycles = load_cycles(world["engine"], CFG, store_root=world["store"])
    assert [c.run_id for c in cycles] == world["runs"]
    c0, c1 = cycles[0], cycles[1]
    kinds = {n.kind for n in c0.nodes}
    assert kinds == {"entry", "lesson", "ltm"}
    ltm_ids = {n.node_id for n in c0.nodes if n.kind == "ltm"}
    assert ltm_ids == {"DA.ltm.1", "DA.ltm.2", "DA.ltm.4"}                # inactive row 3 and the group node excluded
    assert c0.ctx.regime == "RISK-OFF" and c1.ctx.regime == "RISK-ON"
    assert c0.ctx.holdings == ["QCOM"] and c0.ctx.watchlist == ["ISRG", "NET"] and c0.source["holdings"] == "event_snapshot"
    assert c1.ctx.holdings == ["QCOM"] and c1.ctx.watchlist == [] and c1.source["watchlist"] == "unknown"
    assert c0.ctx.news == ["MU"] and c0.ctx.entities == ["NVDA"] and c0.ctx.trend == ["MRVL"]
    assert c0.ctx.event_block.startswith("# EVENT CALENDAR") and c1.ctx.event_block == ""
    assert c0.ctx.quarantined == [] and c1.ctx.quarantined == ["IONQ"]    # sold 2026-09-07 10:00: after c0, before c1
    assert world["cited_rule"] in c0.cited
    assert "DA.memory.log.2026_09_02_regime" in c0.today_ids and c0.source["ltm_today"] == "manifest"
    assert c0.decided_tickers == {"IONQ", "NET"} and "zebra giraffe" in c0.reasons
    pins = c0.pinned_ids()
    assert world["cited_rule"] in pins and "DA.memory.lessons.priced_kill" in pins
    assert "DA.memory.lessons.priced_kill" not in c0.pinned_ids(("entry", "ltm", "lesson"))
    assert len(load_cycles(world["engine"], CFG, store_root=world["store"], limit=5)) == 5


def test_decider_inputs_table_wins_when_present(world):
    eng = world["engine"]
    run = world["runs"][1]
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE decider_inputs (id INTEGER PRIMARY KEY, run_id TEXT, config_hash TEXT, context TEXT)"))
        conn.execute(text("INSERT INTO decider_inputs (run_id, config_hash, context) VALUES (:r, :h, :c)"),
                     {"r": run, "h": CFG, "c": json.dumps({"holdings": ["AMD"], "watchlist": ["ZS"],
                                                            "event_block": "# EVENT CALENDAR exact"})})
    assert decider_inputs_for(eng, [run])[run]["watchlist"] == ["ZS"]
    c = [x for x in load_cycles(eng, CFG, store_root=world["store"]) if x.run_id == run][0]
    assert c.ctx.holdings == ["AMD"] and c.ctx.watchlist == ["ZS"] and c.ctx.event_block == "# EVENT CALENDAR exact"
    assert c.source["holdings"] == "decider_inputs" and c.source["event_block"] == "decider_inputs"


def test_decider_inputs_reads_the_decide_row_not_the_citation_repair_row(world):
    from policy_graph import inputs as I
    eng = world["engine"]
    run = world["runs"][1]                       # no event snapshot: without decider_inputs the watchlist is unknown
    I.ensure_schema(eng)
    # another config's row for the same run id, written first: never read for this config
    I.record_input(eng, "other_cfg", run_id=run, prompt_version=21, context={"regime": "x", "watchlist": ["XX"]})
    did = I.record_input(eng, CFG, run_id=run, prompt_version=21, call_kind=I.CALL_DECIDE,
                         context={"regime": "risk_on", "holdings": ["AAPL"], "watchlist": ["ZS"]})
    I.record_reply(eng, did, {"decisions": [{"action": "hold", "ticker": "CASH", "reason": "no setup clears the gates"}]})
    rid = I.record_input(eng, CFG, run_id=run, prompt_version=21, call_kind=I.CALL_CITATION_REPAIR)   # no context
    I.record_reply(eng, rid, {"citations": {"0": ["DA.ltm.1"]}})
    got = decider_inputs_for(eng, [run], config_hash=CFG)[run]
    assert got["watchlist"] == ["ZS"] and got["holdings"] == ["AAPL"] and got["regime"] == "risk_on"
    c = [x for x in load_cycles(eng, CFG, store_root=world["store"]) if x.run_id == run][0]
    assert c.ctx.watchlist == ["ZS"] and c.ctx.holdings == ["AAPL"] and c.ctx.regime == "risk_on"
    assert c.source["watchlist"] == "decider_inputs" and c.source["holdings"] == "decider_inputs"


def test_decider_inputs_merge_never_lets_a_later_row_erase_context(world):
    eng = world["engine"]                        # a layout without call_kind: rows merge oldest first
    run = world["runs"][1]
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE decider_inputs (id INTEGER PRIMARY KEY, run_id TEXT, config_hash TEXT, context TEXT)"))
        conn.execute(text("INSERT INTO decider_inputs (run_id, config_hash, context) VALUES (:r, :h, :c)"),
                     {"r": run, "h": CFG, "c": json.dumps({"watchlist": ["ZS"]})})
        conn.execute(text("INSERT INTO decider_inputs (run_id, config_hash, context) VALUES (:r, :h, NULL)"), {"r": run, "h": CFG})
        conn.execute(text("INSERT INTO decider_inputs (run_id, config_hash, context) VALUES (:r, :h, :c)"),
                     {"r": run, "h": CFG, "c": json.dumps({"watchlist": ["YY"], "holdings": ["AMD"]})})
    assert decider_inputs_for(eng, [run])[run] == {"watchlist": ["ZS"], "holdings": ["AMD"]}


def test_training_protocol_artifact_and_reports(world, tmp_path):
    cycles = load_cycles(world["engine"], CFG, store_root=world["store"])
    t = fakes.FakeEmbeddingsTransport()
    emb = EmbeddingClient("http://fake/v1", "fake-embed", transport=t)
    art, rep = T.run(cycles, emb, config_hash=CFG, recall_target=0.9, ltm_cap=14, log=lambda *_: None)
    assert art["kind"] == "policy_router" and art["features"] == list(T.FEATURES) and art["embed"]["model"] == "fake-embed"
    assert isinstance(art["certified"], bool)
    crit, passed = T.certify(rep["heldout"], 0.9)
    cert = art["certification"]
    assert art["certified"] == (crit is not None) and cert["criterion"] == crit and cert["criteria"] == passed
    assert passed["target"] == (rep["heldout"]["recall"] is not None and rep["heldout"]["recall"] >= 0.9)
    assert cert["today_recall"] == rep["heldout"]["today_recall"] and cert["chars_today"] == rep["heldout"]["chars_today"]
    assert cert["chars_selected"] == rep["heldout"]["chars_selected"] and cert["llm_model"] is None
    assert art["label"]["mode"] == "marginal" and art["label"]["definition"] == T.MARGINAL_DEFINITION   # the default label
    assert art["certification"]["heldout_cycles"] == 5 and art["certification"]["train_cycles"] == 13
    assert set(rep["lowo_all"]["weeks"]) == {"2026-W37", "2026-W38", "2026-W39"}
    assert rep["label"]["citation_pairs"] >= 18 and 0 < rep["label"]["theta"] <= 1
    stats = rep["label"]["stats"]
    assert stats["entry"]["similar"] > 0                                  # the regime entry echoed in reasons
    assert stats["ltm"]["ticker"] == 0
    h = rep["heldout"]
    assert h["chars_today"] > 0 and h["recall_ceiling"] == pytest.approx(1.0)
    assert {"recall", "today_recall", "chars_selected", "brier", "reliability", "missed"} <= set(h)
    assert "plain" in rep["alternatives"] and set(rep["alternatives"]["plain"]["criteria"]) == {"target", "beats_today"}
    md = T.report_markdown(rep)
    assert "## Verdict" in md and "Needed nodes the router would have missed" in md and "Label: marginal" in md
    assert "beats_today: recall" in md and "| plain |" in md and T.LABEL_DEFINITION in md
    paths = T.write_outputs(tmp_path / "out", art, rep)
    assert json.loads(paths["artifact"].read_text())["model_version"] == art["model_version"]
    assert paths["report_md"].read_text().startswith("# Policy router")
    # the artifact loads and routes at runtime
    from policy_router.runtime import RouterSettings, route_cycle
    s = RouterSettings.from_mapping({"DAI_ROUTER_EMBED_MODEL": "fake-embed"}, repo_root=tmp_path, config_hash=CFG)
    r = route_cycle(s, cycles[-1].ctx, cycles[-1].nodes, embedder=emb, artifact=art)
    assert r.effective_mode == "shadow" and r.selection is not None


def test_plain_label_stays_available(world):
    cycles = load_cycles(world["engine"], CFG, store_root=world["store"])
    emb = EmbeddingClient("http://fake/v1", "fake-embed", transport=fakes.FakeEmbeddingsTransport())
    art, rep = T.run(cycles, emb, config_hash=CFG, recall_target=0.9, label_mode="plain", compare_labels=False,
                     log=lambda *_: None)
    assert art["label"]["mode"] == "plain" and art["label"]["definition"] == T.LABEL_DEFINITION
    assert art["certification"]["label_mode"] == "plain" and rep["alternatives"] == {}


def test_certify_records_target_and_beats_today():
    marginal = {"recall": 0.974, "today_recall": 0.908, "chars_selected": 5854.0, "chars_today": 7587.0}
    assert T.certify(marginal, 0.98) == ("beats_today", {"target": False, "beats_today": True})
    assert T.certify(dict(marginal, recall=0.985), 0.98) == ("target", {"target": True, "beats_today": True})
    plain = {"recall": 0.960, "today_recall": 0.748, "chars_selected": 8288.0, "chars_today": 7587.0}
    assert T.certify(plain, 0.98) == (None, {"target": False, "beats_today": False})        # serves more than today
    assert T.certify(dict(marginal, today_recall=0.98), 0.98)[0] is None                     # below today's recall
    assert T.certify(dict(marginal, chars_selected=7587.0), 0.98)[0] == "beats_today"        # ties count
    assert T.certify(dict(marginal, recall=None), 0.98) == (None, {"target": False, "beats_today": False})


def test_priors_are_leak_free_inside_the_fit_set(world):
    cycles = load_cycles(world["engine"], CFG, store_root=world["store"])
    labels = {c.run_id: {n.node_id: (n.node_id == "DA.ltm.2", "", 0.0) for n in c.nodes} for c in cycles}
    X_by = {c.run_id: np.zeros((len(c.nodes), len(T.FEATURES))) for c in cycles}
    model, priors = T.fit_model(cycles[:6], X_by, labels, strength=4.0)
    assert priors.counts["DA.ltm.2"] == [6, 6] and priors.counts["DA.ltm.1"] == [0, 6]
    p_first = T.predict_cycles(model, T.Priors(strength=4.0), cycles[:1], X_by)[cycles[0].run_id]
    p_later = T.predict_cycles(model, priors, cycles[6:7], X_by)[cycles[6].run_id]
    i2 = [n.node_id for n in cycles[6].nodes].index("DA.ltm.2")
    assert p_later[i2] > p_first[i2]                                      # the prior column carries the history
    with pytest.raises(ValueError):
        T.fit_model(cycles[:3], X_by, {c.run_id: {n.node_id: (False, "", 0.0) for n in c.nodes} for c in cycles})


def test_choose_setting_prefers_cheapest_that_meets_target():
    rows = [{"tau_min": 0.5, "recall_target": 0.9, "recall": 0.97, "chars_selected": 100},
            {"tau_min": 0.6, "recall_target": 0.99, "recall": 0.99, "chars_selected": 300},
            {"tau_min": 0.7, "recall_target": 0.999, "recall": 1.0, "chars_selected": 500}]
    best, met = T.choose_setting(rows, 0.98)
    assert met and best["chars_selected"] == 300
    best, met = T.choose_setting(rows[:1], 0.98)
    assert not met and best["recall"] == 0.97


def test_cli_with_sqlite_and_fake_transport(world, tmp_path, monkeypatch, capsys):
    t = fakes.FakeEmbeddingsTransport()
    real = T.EmbeddingClient
    monkeypatch.setattr(T, "EmbeddingClient", lambda *a, **k: real(*a, **dict(k, transport=t)))
    out = tmp_path / "router-out"
    rc = T.main(["--config-hash", CFG, "--db-url", f"sqlite:///{world['db_path']}", "--repo-root", str(world["root"]),
                 "--out-dir", str(out), "--cache", str(tmp_path / "cache.sqlite3"), "--recall-target", "0.9",
                 "--no-compare"])
    assert rc == 0 and (out / "model.json").exists() and (out / "eval.md").exists() and (out / "eval.json").exists()
    assert json.loads((out / "model.json").read_text())["label"]["mode"] == "marginal"
    assert "held-out recall" in capsys.readouterr().out
    assert T.main(["--config-hash", CFG, "--routable", "bogus"]) == 2
