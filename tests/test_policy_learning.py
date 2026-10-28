"""The learning landscape stays fixed and keeps evidence types separate."""
import hashlib
import json
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from policy_graph import learning as L, service


class LocalVectors:
    model = "test-local"

    def embed(self, texts, **kwargs):
        return np.array([np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8) / 255 for t in texts])


class Offline:
    def embed(self, *args, **kwargs):
        raise RuntimeError("offline")


def landmarks():
    return [{"key": f"rule{i}:rev1", "id": f"rule{i}", "body": t} for i, t in enumerate([
        "Position risk limits and priced stops", "Event calendar earnings and FOMC risk",
        "Buy pullbacks with controlled position size", "Review trade outcomes and lessons",
    ])]


def test_projection_is_frozen_when_rules_arrive_and_endpoint_disappears(tmp_path):
    path = tmp_path / "projection.json"
    first = landmarks()
    meta = L.projection(first, path, embedder=LocalVectors())
    coordinates = {n["key"]: (n["x"], n["y"]) for n in first}
    later = landmarks() + [{"key": "rule0:rev2", "id": "rule0", "body": "Updated position limits"}]
    second = L.projection(later, path, embedder=LocalVectors())
    assert second["id"] == meta["id"] and second["method"] == "semantic_pca"
    assert all((n["x"], n["y"]) == coordinates[n["key"]] for n in later[:-1])
    unavailable = later + [{"key": "rule5:new", "id": "rule5", "body": "An unseen opportunity"}]
    third = L.projection(unavailable, path, embedder=Offline())
    assert third["id"] == meta["id"] and third["pending"] == 1
    assert unavailable[-1]["x"] is None
    assert all((n["x"], n["y"]) == coordinates[n["key"]] for n in unavailable[:4])


def test_lexical_fallback_is_declared_and_does_not_silently_switch_models(tmp_path):
    path = tmp_path / "projection.json"
    first = landmarks()
    meta = L.projection(first, path, embedder=Offline())
    assert meta["method"] == "lexical_pca" and "shared words" in meta["note"]
    second = landmarks() + [{"key": "new", "id": "new", "body": "A new earnings lesson"}]
    newer = L.projection(second, path, embedder=LocalVectors())
    assert newer["id"] == meta["id"] and newer["method"] == "lexical_pca"
    assert [(n["x"], n["y"]) for n in first] == [(n["x"], n["y"]) for n in second[:-1]]
    assert all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in second)


def test_changed_embedding_dimension_leaves_new_points_pending(tmp_path):
    class Other(LocalVectors):
        def embed(self, texts, **kwargs):
            return np.ones((len(texts), 4))
    path = tmp_path / "projection.json"
    L.projection(landmarks(), path, embedder=LocalVectors())
    later = landmarks() + [{"key": "new", "id": "new", "body": "New rule"}]
    meta = L.projection(later, path, embedder=Other())
    assert meta["pending"] == 1 and later[-1]["x"] is None


def test_different_embedding_model_cannot_reuse_the_same_dimension_basis(tmp_path):
    class OtherModel(LocalVectors):
        model = "different-model-same-dimension"
        def embed(self, *args, **kwargs):
            raise AssertionError("An incompatible model must never be queried")
    path = tmp_path / "projection.json"
    L.projection(landmarks(), path, embedder=LocalVectors())
    later = landmarks() + [{"key": "new", "id": "new", "body": "New rule"}]
    meta = L.projection(later, path, embedder=OtherModel())
    assert meta["pending"] == 1 and later[-1]["x"] is None
    assert "model changed" in meta["note"] and meta["embedding_model"] == "test-local"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE prompt_versions (id INTEGER PRIMARY KEY, config_hash TEXT,
            agent_type TEXT, version INTEGER, system_prompt TEXT, user_prompt_template TEXT,
            strategy_directives TEXT, soul TEXT, memory TEXT, description TEXT, created_by TEXT,
            is_active BOOLEAN, created_at TIMESTAMP)"""))
        for version, rule in [(0, "1. REGIME GATE — pass in risk off."),
                              (1, "1. REGIME GATE — selective half size entries."),
                              (2, "2. PRICED KILL — use a numeric stop.")]:
            conn.execute(text("""INSERT INTO prompt_versions VALUES (:id,'test','DeciderAgent',:v,
                'system','template',:rules,'## Mission\nSeek controlled opportunities.',
                '## Lessons\n- **#risk — keep a priced stop.**','Policy update','human',:active,:at)"""),
                         {"id": version + 1, "v": version, "rules": "## Current Strategy\n" + rule + "\n9. ACCOUNT LIMITS — keep the cash buffer.",
                          "active": version == 2, "at": datetime(2026, 10, 20 + version)})
    yield engine
    engine.dispose()


def test_history_tracks_exact_revisions_and_retirement_without_mutating_source(db, tmp_path):
    ctx = service._Ctx(db, "test", tmp_path, False)
    nodes, versions = L.history(ctx, "DeciderAgent")
    regimes = [n for n in nodes if n["id"].endswith("regime_gate")]
    assert len(regimes) == 2 and regimes[0]["versions"] == [0] and regimes[1]["versions"] == [1]
    assert regimes[0]["key"] != regimes[1]["key"]
    assert "DA.directives.strategy.regime_gate" in versions[1]["changes"]["changed"]
    assert "DA.directives.strategy.regime_gate" in versions[2]["changes"]["removed"]
    mission = next(n for n in nodes if n["id"] == "DA.soul.mission")
    assert mission["versions"] == [0, 1, 2]
    assert all(n["field"] in ("soul", "strategy_directives", "memory") for n in nodes)
    assert not any(n["node_type"] in ("root", "field", "ltm") for n in nodes)
    assert not (tmp_path / "agents/decider/policy-graph").exists()


def test_payload_empty_evidence_is_not_zero_performance(db, tmp_path):
    result = L.learning_payload(db, "test", "DeciderAgent", 1, repo_root=tmp_path, embedder=Offline())
    assert result["selected_version"] == 1 and len(result["versions"]) == 3
    assert result["opportunities"]["cases"] == [] and result["replays"]["runs"] == []
    assert result["opportunities"]["metrics_by_horizon"]["3"]["recall"] is None
    assert result["evidence"] == []
    assert result["theme_method"]["id"] == "market_themes_v1"
    assert {theme["id"] for theme in result["theme_catalog"]} >= {"geopolitics_iran", "energy_oil", "ai", "memory_manufacturing", "electric_vehicles"}
    assert all(theme["case_count"] == 0 for theme in result["theme_catalog"])
    assert all(node["market_themes"] == ["general"] for node in result["landmarks"])
    with pytest.raises(service.NotFound):
        L.learning_payload(db, "test", "DeciderAgent", 999, repo_root=tmp_path, embedder=Offline())
    with pytest.raises(service.BadRequest):
        L.learning_payload(db, "../other", "DeciderAgent", 1, repo_root=tmp_path, embedder=Offline())
    with pytest.raises(service.NotFound):
        L.learning_payload(db, "other", "DeciderAgent", 1, repo_root=tmp_path, embedder=Offline())


def test_historical_evidence_never_exposes_raw_prompts_and_is_not_recall_coverage(db):
    from policy_graph import inputs
    inputs.ensure_schema(db)
    iid = inputs.record_input(db, "test", run_id="r1", prompt_version=2,
                              system_prompt="private account snapshot", user_prompt="private holdings",
                              context={"regime": "MIXED"})
    inputs.record_reply(db, iid, {"decisions": [{"ticker": "AAA", "action": "BUY",
                         "reason": "Setup [cites: DA.directives.strategy.priced_kill]"}],
                         "considered": [{"ticker": "BBB", "action": "PASS", "reason": "No setup"}]})
    cases = L._evidence(db, "test")
    assert len(cases) == 2 and cases[0]["cited"] == ["DA.directives.strategy.priced_kill"]
    assert not any(n["eligible_for_recall"] for n in cases)
    assert "private" not in json.dumps(cases)
    assert L._evidence(db, "other") == []


def test_payload_links_market_topics_to_same_version_without_changing_quality_or_projection(db, tmp_path):
    from policy_graph import inputs
    inputs.ensure_schema(db)
    iid = inputs.record_input(db, "test", run_id="market-r1", prompt_version=1,
                              system_prompt="private", user_prompt="private", context={"regime": "MIXED"})
    rule_id = "DA.directives.strategy.regime_gate"
    inputs.record_reply(db, iid, {"considered": [{"ticker": "MU", "verdict": "reject",
        "why": "No qualifying entry", "signals": "DRAM pricing and HBM demand supplied.", "cited": [rule_id]}]})
    first = L.learning_payload(db, "test", "DeciderAgent", 2, repo_root=tmp_path, embedder=Offline())
    old, newer = sorted((n for n in first["landmarks"] if n["id"] == rule_id), key=lambda n:n["first_version"])
    assert old["market_themes"] == ["general"]
    assert "memory_manufacturing" in newer["linked_market_themes"]
    assert newer["direct_market_themes"] == []
    assert "HBM" in first["evidence"][0]["signals"]
    assert first["opportunities"]["metrics"]["recall"] is None
    second = L.learning_payload(db, "test", "DeciderAgent", 1, repo_root=tmp_path, embedder=Offline())
    assert first["projection"]["id"] == second["projection"]["id"]
    assert {(n["key"], n["x"], n["y"]) for n in first["landmarks"]} == {(n["key"], n["x"], n["y"]) for n in second["landmarks"]}
    assert first["opportunities"]["metrics"] == second["opportunities"]["metrics"]


def test_route_validates_input_and_disables_cache(db, tmp_path, monkeypatch):
    from flask import Flask
    from policy_graph.routes import register_policy_graph_routes
    monkeypatch.setattr(L, "EmbeddingClient", lambda **kwargs: Offline())
    app = Flask(__name__)
    register_policy_graph_routes(app, engine=db, get_config_hash=lambda: "test", repo_root=tmp_path,
                                 is_margin_account=False)
    client = app.test_client()
    response = client.get("/api/policy-graph/learning?agent=DeciderAgent&version=2")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["selected_version"] == 2
    assert client.get("/api/policy-graph/learning?days=0").status_code == 400
    assert client.get("/api/policy-graph/learning?agent=Unknown").status_code == 400
    assert client.get("/api/policy-graph/learning?version=999").status_code == 404


def test_explicit_replay_routes_scope_jobs_and_block_overlap(db, tmp_path, monkeypatch):
    from flask import Flask
    import threading
    import time
    from policy_graph import learning_replay as R
    from policy_graph.routes import register_policy_graph_routes
    entered, release = threading.Event(), threading.Event()
    config = {"id": "test"}
    seen = []
    monkeypatch.setattr(R, "preview_comparison", lambda *args, **kwargs: {
        "compatible": True, "cohort_hash": "a" * 64, "model_calls": 2})
    def execute(engine, cfg, runner, expected_cohort_hash, **kwargs):
        assert expected_cohort_hash == "a" * 64
        entered.set()
        assert release.wait(3)
        runner({"source_input_id": 1, "side": "candidate"})
        return {"id": 7, "cases": [], "status": "ok"}
    monkeypatch.setattr(R, "run_comparison", execute)
    app = Flask(__name__)
    register_policy_graph_routes(app, engine=db, get_config_hash=lambda: config["id"], repo_root=tmp_path,
                                 is_margin_account=False, learning_runner=lambda request: seen.append(request))
    client = app.test_client()
    body = {"source_input_ids": [1], "candidate_version": 2, "expected_cohort_hash": "a" * 64}
    assert client.post("/api/policy-graph/learning/replay-preview", json=body).status_code == 200
    # Neither preview nor an invalid/stale request can invoke a model.
    assert seen == []
    stale = {**body, "expected_cohort_hash": "b" * 64}
    assert client.post("/api/policy-graph/learning/replay", json=stale).status_code == 409
    response = client.post("/api/policy-graph/learning/replay", json=body)
    assert response.status_code == 202 and entered.wait(1)
    job = response.get_json()["job_id"]
    assert client.post("/api/policy-graph/learning/replay", json=body).status_code == 409
    config["id"] = "other"
    assert client.get(f"/api/policy-graph/learning/replay-jobs/{job}").status_code == 404
    release.set()
    config["id"] = "test"
    for _ in range(100):
        result = client.get(f"/api/policy-graph/learning/replay-jobs/{job}")
        if result.get_json()["status"] == "complete":
            break
        time.sleep(.01)
    assert result.get_json()["result"]["id"] == 7
    assert result.headers["Cache-Control"] == "no-store"
    assert seen[0]["config_hash"] == "test"


def test_replay_preview_rejects_cross_origin_and_unbounded_requests(db, tmp_path):
    from flask import Flask
    from policy_graph.routes import register_policy_graph_routes
    app = Flask(__name__)
    register_policy_graph_routes(app, engine=db, get_config_hash=lambda: "test", repo_root=tmp_path,
                                 is_margin_account=False)
    client = app.test_client()
    valid = {"source_input_ids": [1], "candidate_version": 2}
    assert client.post("/api/policy-graph/learning/replay-preview", json=valid,
                       headers={"Origin": "https://unrelated.example"}).status_code == 400
    assert client.post("/api/policy-graph/learning/replay-preview", json={**valid,"source_input_ids":list(range(1,8))}).status_code == 400
    assert client.post("/api/policy-graph/learning/replay-preview", json={**valid,"candidate_version":True}).status_code == 400
    assert client.post("/api/policy-graph/learning/replay-preview", json={**valid,"outcome_spec":{"horizon":True}}).status_code == 400
    assert client.post("/api/policy-graph/learning/replay-preview", json={**valid,"padding":"x"*17000}).status_code == 400
