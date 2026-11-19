import json
import pytest
from sqlalchemy import create_engine, text

from policy_graph.learning_replay import ReplayError
from policy_router.replay import INDEX_HEADER, MEMORY_HEADER, memory_lines, routed_prompt


def fixture():
    engine = create_engine("sqlite://")
    lines = "- [lesson] First ⟨DA.ltm.1⟩\n- [lesson] Second ⟨DA.ltm.2 · cited 7d/30d/90d: 1/2/3⟩\n"
    prompt = "Cycle data\n\n" + MEMORY_HEADER + lines + "\nActivity\n\n" + INDEX_HEADER + "DA.rule — Protected\nDA.ltm.1 — First\nDA.ltm.2 — Second\n\nScreenshot context"
    source = dict(id=4, run_id="run", prompt_version=62, user_prompt=prompt, ltm_ids="[1,2]")
    nodes = [dict(node_id=f"DA.ltm.{i}",kind="ltm",served_in_prompt=True,decisions_choice=d,decisions_p=p)
             for i,d,p in [(1,"exclude",0.01),(2,"include",0.99)]]
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE policy_router_comparisons(config_hash,run_id,source_input_id,prompt_version,source_kind,status,nodes_json,comparison_json)"))
        conn.execute(text("INSERT INTO policy_router_comparisons VALUES ('cfg','run',4,62,'live','ok',:n,'{}')"),{"n":json.dumps(nodes)})
    return engine,source


def test_omits_only_frozen_body_and_index_and_never_uses_current_db_memory():
    engine,source=fixture()
    result,ids=routed_prompt(engine,"cfg",source)
    assert result==source["user_prompt"].replace("- [lesson] First ⟨DA.ltm.1⟩\n","").replace("DA.ltm.1 — First\n","")
    assert ids==["DA.ltm.1"]
    with pytest.raises(ReplayError):
        routed_prompt(engine,"other",source)


def test_missing_memory_body_or_ambiguous_selection_fails_closed():
    engine,source=fixture()
    with pytest.raises(ReplayError):
        memory_lines(dict(source,ltm_ids="[1]"))
    with engine.begin() as conn:
        conn.execute(text("UPDATE policy_router_comparisons SET comparison_json=:v"),{"v":json.dumps({"applied":True})})
    with pytest.raises(ReplayError):
        routed_prompt(engine,"cfg",source)


def test_router_image_pilot_keeps_the_same_evidence_and_records_only_replay(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import router_image_replay as pilot
    from cycle_images import FrozenImage, FrozenImageBundle

    engine, source = fixture()
    source.update(system_prompt="Standing policy ⟨DA.rule⟩", decided_at="2026-11-10T10:00:00",
                  context_json='{"regime":"RISK-OFF","watchlist":["TEST"]}')
    attachments = tuple(
        FrozenImage(str(i), "Source", "17", "summary-run", "image.png", "abc", 1, 1, b"mock")
        for i in range(2)
    )
    images = FrozenImageBundle("cfg", "run", attachments, len(attachments))
    monkeypatch.setattr(pilot, "_source_inputs", lambda *args: [source])
    monkeypatch.setattr(pilot, "_source_image_bundle", lambda *args: images)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE summaries (id, config_hash, run_id, agent, timestamp, data)"))
        conn.execute(text("CREATE TABLE event_risk_snapshots (config_hash, run_id, as_of, block)"))
        conn.execute(text("""
            INSERT INTO summaries VALUES (17,'cfg','summary-run','Source','2026-11-10T09:00:00',:data)
        """), {"data": json.dumps({"summary": {"headlines": ["Original headline"]}})})

    requests, records = [], []
    def score(settings, context, nodes, **kwargs):
        requests.append((context.text(), tuple(node.node_id for node in nodes), kwargs))
        chosen = nodes[:1] if kwargs["image_bundle"] is None else nodes
        selection = SimpleNamespace(included=chosen, include_ids={n.node_id for n in chosen})
        return SimpleNamespace(status="ok", cost_usd=.001, latency_ms=43, selection=selection)
    def record(*args, **kwargs):
        records.append(kwargs)
        return len(records)
    monkeypatch.setattr(pilot, "route_shadow_cycle", score)
    monkeypatch.setattr(pilot, "record_shadow", record)

    preview = pilot.run(engine, "cfg", 4, screenshot_root=tmp_path)
    assert preview["summaries"] == 1 and preview["images"] == 2 and not requests
    result = pilot.run(engine, "cfg", 4, screenshot_root=tmp_path, execute=True)
    assert result["changed_selections"] == ["DA.ltm.2"]
    assert "Original headline" in requests[0][0]
    assert requests[0][:2] == requests[1][:2]
    assert requests[0][2]["pinned_policy"] == requests[1][2]["pinned_policy"] == source["system_prompt"]
    assert requests[0][2]["image_bundle"] is None and requests[1][2]["image_bundle"] == images
    assert all(r["source_kind"] == "replay" and r["source_input_id"] == 4 for r in records)

    with engine.begin() as conn:
        conn.execute(text("UPDATE summaries SET timestamp='2026-11-11T15:00:00'"))
    with pytest.raises(ReplayError, match="no usable text"):
        pilot.run(engine, "cfg", 4, screenshot_root=tmp_path, execute=True)
    assert len(requests) == 2
