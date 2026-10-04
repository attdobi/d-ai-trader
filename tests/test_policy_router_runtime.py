"""policy_router.runtime / log / panel: settings from a mapping, the off | shadow | active contract, every
fallback path (missing artifact, embedding timeout, endpoint down, embed-model mismatch, malformed artifact),
the certification gate, the per-node log + shadow recall on SQLite, and the Router panel route."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from policy_router import log as rlog
from policy_router.embed import EmbeddingClient
from policy_router.features import FEATURES, Priors
from policy_router.model import LogisticModel
from policy_router.panel import router_panel
from policy_router.runtime import (RouterSettings, artifact_path, certification_gaps, load_artifact, route_cycle)

_spec = importlib.util.spec_from_file_location("policy_router_fakes", Path(__file__).resolve().parent / "policy_router_fakes.py")
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)

CFG = "cfg_router"


def make_artifact(*, certified=True, target=0.98, routable=("entry", "ltm"), ltm_cap=14, embed_model="m"):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, len(FEATURES)))
    y = (X[:, FEATURES.index("cos_ctx")] > 0).astype(float)
    model = LogisticModel(l2=1.0, class_weight="balanced").fit(X, y, feature_names=FEATURES)
    return {"schema": 1, "kind": "policy_router", "model_version": "abc123def456", "certified": certified,
            "embed": {"model": embed_model, "query_prefix": "search_query: ", "doc_prefix": "search_document: "},
            "features": list(FEATURES), "model": model.to_dict(), "priors": Priors().to_dict(),
            "selection": {"tau_min": 0.6, "recall_target": 0.9, "min_per_kind": {}, "max_per_kind": {"ltm": ltm_cap}},
            "routable": list(routable),
            "certification": {"target": target, "certified": certified, "heldout_recall": 0.99 if certified else 0.9,
                              "routable": list(routable), "ltm_cap": ltm_cap},
            "heldout": {"recall": 0.99, "today_recall": 0.8, "chars_selected": 500.0, "chars_today": 900.0,
                        "chars_routable": 1200.0, "chars_reduction_vs_today": 0.44, "brier": 0.08}}


def nodes():
    return [fakes.node("DA.memory.log.2026_09_24", "entry", "MU priced kill worries in RISK-ON", tickers=["MU"]),
            fakes.node("DA.memory.log.2026_06_01", "entry", "old unrelated diary words"),
            fakes.node("DA.ltm.7", "ltm", "- [mistake] (QCOM) QCOM chase", tickers=["QCOM"], weight=1.5),
            fakes.node("DA.ltm.8", "ltm", "- [rule] zebra giraffe", weight=1.0),
            fakes.node("DA.memory.lessons.regime", "lesson", "lesson text pinned when lessons are not routable")]


def settings(tmp_path, **env):
    base = {"DAI_POLICY_ROUTER": "shadow", "DAI_ROUTER_EMBED_MODEL": "m"}
    base.update(env)
    return RouterSettings.from_mapping(base, repo_root=tmp_path, config_hash=CFG)


def embedder(**kw):
    return EmbeddingClient("http://fake/v1", "m", transport=fakes.FakeEmbeddingsTransport(**kw))


def write_artifact(tmp_path, art):
    p = artifact_path(tmp_path, CFG)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(art))
    return p


# ----------------------------------------------------------------------------- settings
def test_settings_from_mapping_defaults_and_parsing(tmp_path):
    s = RouterSettings.from_mapping({}, repo_root=tmp_path, config_hash=CFG)
    assert (s.mode, s.base_url, s.embed_model, s.llm_model, s.recall_target, s.routable, s.ltm_limit) == (
        "shadow", "http://127.0.0.1:1234/v1", "text-embedding-nomic-embed-text-v1.5", "", 0.98, ("entry", "ltm"), 14)
    assert s.embed_budget_s == 5.0 and s.llm_budget_s == 15.0
    assert s.artifact_path == tmp_path / "agents" / "decider" / "policy-router" / CFG / "model.json"
    s = RouterSettings.from_mapping({"DAI_POLICY_ROUTER": "OFF", "DAI_ROUTER_ROUTABLE": "lesson, entry ,bogus",
                                     "DAI_ROUTER_RECALL_TARGET": "1.7", "DAI_MEMORY_LT_LIMIT": "9",
                                     "DAI_ROUTER_LLM_MODEL": " qwen "}, repo_root=tmp_path, config_hash=CFG)
    assert s.mode == "off" and s.routable == ("lesson", "entry") and s.recall_target == 1.0 and s.ltm_limit == 9
    assert s.llm_model == "qwen"
    assert RouterSettings.from_mapping({"DAI_POLICY_ROUTER": "active"}, repo_root=tmp_path, config_hash=CFG).mode == "active"
    assert RouterSettings.from_mapping({"DAI_POLICY_ROUTER": "weird"}, repo_root=tmp_path, config_hash=CFG).mode == "shadow"


# ----------------------------------------------------------------------------- modes and fallbacks
def test_off_returns_none(tmp_path):
    assert route_cycle(settings(tmp_path, DAI_POLICY_ROUTER="off"), fakes.context(), nodes()) is None


def test_missing_artifact_falls_back(tmp_path):
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder())
    assert r.effective_mode == "fallback" and r.backend == "fallback" and r.selection is None
    assert "no router model" in r.note and "policy_router.train" in r.note
    assert r.summary_line().startswith("🧭 Policy router fallback (today's prompt served)")
    assert not r.active and r.assembly_override() == {} and r.ltm_tail_line() == ""


def test_shadow_scores_routable_nodes_only_and_reports_today(tmp_path):
    write_artifact(tmp_path, make_artifact())
    today = {"DA.memory.log.2026_09_24", "DA.ltm.7", "DA.ltm.8"}
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), today_ids=today, embedder=embedder())
    assert r.effective_mode == "shadow" and r.backend == "embed" and r.certified
    ids = {d.node_id for d in r.selection.decisions}
    assert "DA.memory.lessons.regime" not in ids and len(ids) == 4       # lessons are pinned by default
    assert all(0.0 <= d.p <= 1.0 and d.choice in ("include", "exclude") for d in r.selection.decisions)
    assert r.chars_today == sum(n.chars for n in nodes() if n.node_id in today)
    assert r.model_version == "abc123def456" and r.latency_ms >= 0
    assert "shadow" in r.summary_line()


def test_active_requires_a_certified_artifact(tmp_path):
    write_artifact(tmp_path, make_artifact(certified=False))
    r = route_cycle(settings(tmp_path, DAI_POLICY_ROUTER="active"), fakes.context(), nodes(), embedder=embedder())
    assert r.effective_mode == "shadow" and not r.active and "not certified" in r.note


def test_active_with_certified_artifact_exposes_override_ltm_choice_and_tail(tmp_path):
    write_artifact(tmp_path, make_artifact())
    r = route_cycle(settings(tmp_path, DAI_POLICY_ROUTER="active", DAI_MEMORY_LT_LIMIT="14"), fakes.context(), nodes(),
                    embedder=embedder())
    assert r.active and r.note == ""
    ov = r.assembly_override()
    assert set(ov) == {"DA.memory.log.2026_09_24", "DA.memory.log.2026_06_01"}
    assert set(r.ltm_selected_ids()) | set(r.ltm_excluded_ids()) == {"DA.ltm.7", "DA.ltm.8"}
    assert set(r.routable_ids()) == set(ov) | {"DA.ltm.7", "DA.ltm.8"}
    # a one-row memory cap (certified for it) forces one memory row out → named in the tail line
    write_artifact(tmp_path, make_artifact(ltm_cap=1))
    r = route_cycle(settings(tmp_path, DAI_POLICY_ROUTER="active", DAI_MEMORY_LT_LIMIT="1"), fakes.context(), nodes(),
                    embedder=embedder())
    assert r.active and len(r.ltm_selected_ids()) <= 1 and r.ltm_excluded_ids()
    tail = r.ltm_tail_line()
    assert tail.startswith("Memory rows not shown this cycle (routed out") and all(i in tail for i in r.ltm_excluded_ids())


@pytest.mark.parametrize("env,gap", [
    ({"DAI_ROUTER_RECALL_TARGET": "0.99"}, "DAI_ROUTER_RECALL_TARGET"),
    ({"DAI_ROUTER_ROUTABLE": "entry,ltm,lesson"}, "certified for routable"),
    ({"DAI_MEMORY_LT_LIMIT": "5"}, "DAI_MEMORY_LT_LIMIT"),
])
def test_certification_gaps_keep_active_in_shadow(tmp_path, env, gap):
    art = make_artifact()
    s = settings(tmp_path, DAI_POLICY_ROUTER="active", **env)
    assert any(gap in g for g in certification_gaps(art, s))
    r = route_cycle(s, fakes.context(), nodes(), embedder=embedder(), artifact=art)
    assert r.effective_mode == "shadow" and gap in r.note


def test_embedding_timeout_and_endpoint_down_fall_back(tmp_path):
    write_artifact(tmp_path, make_artifact())
    s = settings(tmp_path)
    s.embed_budget_s = 0.1
    r = route_cycle(s, fakes.context(), nodes(), embedder=embedder(delay=0.5))
    assert r.effective_mode == "fallback" and "embedding timeout" in r.note and r.latency_ms < 1000
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(),
                    embedder=embedder(fail=ConnectionRefusedError("refused")))
    assert r.effective_mode == "fallback" and "EmbedError" in r.note


def test_embed_model_mismatch_and_malformed_artifact_fall_back(tmp_path):
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder(),
                    artifact=make_artifact(embed_model="other-model"))
    assert r.effective_mode == "fallback" and "other-model" in r.note
    p = artifact_path(tmp_path, CFG)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"kind": "something-else"}')
    with pytest.raises(ValueError):
        load_artifact(p)
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder())
    assert r.effective_mode == "fallback" and "ValueError" in r.note


def test_llm_tier_refines_uncertain_nodes(tmp_path):
    class Tier:
        def refine(self, ctx_text, items):
            return {items[0][0]: 0.999}, {"answered": 1}
    write_artifact(tmp_path, make_artifact())
    r = route_cycle(settings(tmp_path, DAI_ROUTER_LLM_MODEL="local-chat"), fakes.context(), nodes(), embedder=embedder(),
                    llm=Tier())
    assert r.backend == "embed+llm" and r.llm == {"answered": 1}
    refined = [d for d in r.selection.decisions if d.p_base is not None]
    assert len(refined) == 1 and refined[0].p == pytest.approx(0.999)


# ----------------------------------------------------------------------------- log + shadow recall + panel
@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    from policy_graph.citations import ensure_hits_schema
    ensure_hits_schema(eng)
    yield eng
    eng.dispose()


def test_record_routing_and_shadow_recall(tmp_path, engine):
    write_artifact(tmp_path, make_artifact())
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), today_ids={"DA.ltm.7"}, embedder=embedder())
    n = rlog.record_routing(engine, CFG, 46, "RUN1", r, served_ids={"DA.ltm.7", "DA.memory.log.2026_09_24"})
    assert n == 4
    rows = rlog.run_decisions(engine, CFG, "RUN1")
    assert {x["node_id"] for x in rows} == {d.node_id for d in r.selection.decisions}
    served = {x["node_id"]: x["served_in_prompt"] for x in rows}
    assert served["DA.ltm.7"] is True and served["DA.ltm.8"] is False
    run = rlog.recent_runs(engine, CFG)[0]
    assert run["effective_mode"] == "shadow" and run["backend"] == "embed" and run["chars_today"] == r.chars_today
    assert run["chars_saved"] == r.chars_today - r.selection.chars_selected and run["certified"] is True
    # the Decider cited DA.ltm.7 on that run → explicit shadow recall
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO policy_graph_hits (config_hash, agent_type, run_id, node_id, route, served, cited)
                             VALUES (:h, 'DeciderAgent', 'RUN1', 'DA.ltm.7', 'ltm', :t, :t)"""), {"h": CFG, "t": True})
    sh = rlog.shadow_recall(engine, CFG, last_n=10)
    kept = r.choice("DA.ltm.7")
    assert sh["runs"] == 1 and sh["cited"] == 1 and sh["today_kept"] == 1
    assert sh["router_kept"] == int(bool(kept)) and sh["recall"] == float(bool(kept))
    # a fallback cycle is logged (summary row, no node rows) and ignored by shadow recall
    fb = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder(fail=OSError("down")))
    assert rlog.record_routing(engine, CFG, 46, "RUN2", fb) == 0
    assert rlog.recent_runs(engine, CFG)[0]["effective_mode"] == "fallback"
    assert rlog.shadow_recall(engine, CFG)["runs"] == 1


def test_panel_payload_and_route(tmp_path, engine):
    empty = router_panel(engine, CFG, repo_root=tmp_path)
    assert empty["artifact"] is None and empty["mode"] is None and "no trained model" in empty["note"]
    write_artifact(tmp_path, make_artifact())
    r = route_cycle(settings(tmp_path), fakes.context(), nodes(), embedder=embedder())
    rlog.record_routing(engine, CFG, 46, "RUN1", r, served_ids=set())
    out = router_panel(engine, CFG, repo_root=tmp_path)
    assert out["mode"] == "shadow" and out["effective_mode"] == "shadow" and out["artifact"]["certified"] is True
    assert out["artifact"]["heldout_recall"] == 0.99 and len(out["last_cycle"]["nodes"]) == 4
    assert "Shadow" in out["note"]

    from flask import Flask
    from policy_graph.routes import register_policy_graph_routes
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent.parent / "templates"))
    register_policy_graph_routes(app, engine=engine, get_config_hash=lambda: CFG, repo_root=tmp_path,
                                 is_margin_account=False)
    client = app.test_client()
    res = client.get("/api/policy-graph/router?agent=DeciderAgent&n=5")
    assert res.status_code == 200 and res.get_json()["effective_mode"] == "shadow"
    res = client.get("/api/policy-graph/router?agent=FeedbackAgent")
    assert res.status_code == 200 and res.get_json()["empty"] is True
    assert client.get("/api/policy-graph/router?agent=Nope").status_code == 400
