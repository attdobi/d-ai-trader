"""Visual observations stay scoped research with immutable server provenance."""
from copy import deepcopy
import json

import pytest
from sqlalchemy import create_engine, event, text

from visual_learning import normalize_observations, recent_visual_context


def manifest(cfg="cfg", run="run-1", count=1):
    return {"schema_version": 1, "config_hash": cfg, "decision_run_id": run, "image_count": count,
            "images": [{"image_id": f"I{i:02}", "source_agent": "Agent_CNBC", "summary_id": "42",
                        "source_run_id": "20261029T083047", "sha256": str(i) * 64,
                        "relative_path": f"private/{i}.png", "data_url": "data:image/png;base64,LOCAL_ONLY"}
                       for i in range(1, count + 1)]}


def observation(**changes):
    value = {"image_id": "I01", "ticker": "TSLA", "observed_cues": ["A smiling portrait appears next to a negative headline."],
             "editorial_framing": "mixed", "confidence": "low", "photo_status": "unknown",
             "caveat": "Photo date and the subject's actual reaction are unknown."}
    return dict(value, **changes)


def test_observations_copy_only_server_provenance_and_label_model_uncertainty():
    raw = {"visual_context": [observation(extra="ignore", source_agent="Agent_CNBC")]}
    local = manifest()
    before = deepcopy((raw, local))
    value = normalize_observations(raw, local)
    assert (raw, local) == before
    assert not value["rejected"] and len(value["observations"]) == 1
    accepted = value["observations"][0]
    assert accepted["sha256"] == "1" * 64 and accepted["summary_id"] == "42"
    assert accepted["record_kind"] == "model_observation_not_verified"
    assert accepted["ticker_association"] == "model_reported_caption_or_headline"
    assert accepted["hypothesis_id"].startswith("visual-v1:")
    assert not {"extra", "relative_path", "data_url"} & set(accepted)
    assert "LOCAL_ONLY" not in json.dumps(value)


@pytest.mark.parametrize("change,reason", [
    ({"image_id": "I12"}, "unknown_image_id"),
    ({"image_id": []}, "unknown_image_id"),
    ({"source_agent": "Other source"}, "provenance_mismatch"),
    ({"sha256": "f" * 64}, "provenance_mismatch"),
    ({"source_run_id": "another-run"}, "provenance_mismatch"),
    ({"hypothesis_id": "approved-existing-rule"}, "reserved_hypothesis_id"),
    ({"editorial_framing": "smug"}, "invalid_editorial_framing"),
    ({"editorial_framing": []}, "invalid_editorial_framing"),
    ({"confidence": 1}, "invalid_confidence"),
    ({"photo_status": "definitely_reused"}, "invalid_photo_status"),
    ({"observed_cues": []}, "invalid_observed_cues"),
    ({"observed_cues": ["Authorization: Bearer private-key"]}, "invalid_observed_cues"),
    ({"caveat": ""}, "missing_or_invalid_caveat"),
    ({"ticker": "UNKNOWN"}, "invalid_ticker"),
    ({"ticker": {"name": "TSLA"}}, "invalid_ticker"),
])
def test_unknown_ids_forged_metadata_and_invalid_schema_are_rejected(change, reason):
    value = normalize_observations({"visual_context": [observation(**change)]}, manifest())
    assert value["observations"] == []
    assert value["rejected"][0]["reason"] == reason


def test_absent_observations_are_valid_and_duplicate_manifest_fails_closed():
    assert not normalize_observations({}, None)["rejected"]
    assert not normalize_observations({"visual_context": []}, None)["observations"]
    local = manifest(count=2)
    local["images"][1]["image_id"] = "I01"
    result = normalize_observations({"visual_context": [observation()]}, local)
    assert result["rejected"][0]["reason"] == "missing_or_ambiguous_image_manifest"


@pytest.mark.parametrize("marker", ["data:image/png;BASE64,dGVzdA==", "data:application/octet-stream,bytes",
                                    "image://private/pixels", "image_url", "input_image", "base64"])
def test_research_text_never_forwards_image_payload_markers(marker):
    for changes in ({"observed_cues": [marker]}, {"caveat": marker}):
        result = normalize_observations({"visual_context": [observation(**changes)]}, manifest())
        assert not result["observations"]
        assert marker not in json.dumps(result)
    local = manifest()
    local["images"][0]["source_agent"] = marker
    result = normalize_observations({"visual_context": [observation()]}, local)
    assert not result["observations"]
    assert result["rejected"][0]["reason"] == "missing_or_ambiguous_image_manifest"


def test_dedup_and_bounds_do_not_turn_many_crops_into_independent_research():
    same = observation()
    other = observation(caveat="The actual photo date is not shown.")
    values = [same, same, other, observation(caveat="Another interpretation.")] + [same] * 30
    out = normalize_observations({"visual_context": values}, manifest())
    assert len(out["observations"]) == 2
    assert {item["reason"] for item in out["rejected"]} >= {"duplicate_observation", "per_image_observation_limit", "observation_limit"}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE decider_inputs(id INTEGER PRIMARY KEY,config_hash TEXT,run_id TEXT,prompt_version INTEGER,call_kind TEXT,decided_at TEXT,context_json TEXT,raw_reply TEXT)"))
        c.execute(text("CREATE TABLE learning_opportunities(id INTEGER,config_hash TEXT,input_id INTEGER,ticker TEXT)"))
        c.execute(text("CREATE TABLE learning_opportunity_outcomes(opportunity_id INTEGER,horizon INTEGER,status TEXT,outcome_json TEXT)"))
    return engine


def save(engine, ident, *, cfg="cfg", call="decide", local=None, observations=None):
    with engine.begin() as c:
        c.execute(text("INSERT INTO decider_inputs VALUES(:i,:h,:r,61,:call,'2026-10-29T12:00:00-07:00',:ctx,:reply)"), {
            "i": ident, "h": cfg, "r": f"run-{ident}", "call": call,
            "ctx": json.dumps({"image_manifest": local if local is not None else manifest(cfg, f"run-{ident}")}),
            "reply": json.dumps({"visual_context": observations or [observation()], "secret_extra": "must not be returned"}),
        })


def test_report_read_only_scoped_and_links_only_exact_prospective_input_ticker(db):
    save(db, 1)
    save(db, 2, cfg="other")
    save(db, 3, call="citation_repair")
    save(db, 4, local=manifest("other", "run-4"))
    save(db, 5, local=manifest("cfg", "wrong-run"))
    with db.begin() as c:
        for ident, cfg, source, ticker in [(11, "cfg", 1, "TSLA"), (12, "cfg", 99, "TSLA"),
                                            (13, "cfg", 1, "MSFT"), (14, "other", 1, "TSLA")]:
            c.execute(text("INSERT INTO learning_opportunities VALUES(:i,:h,:source,:ticker)"),
                      {"i": ident, "h": cfg, "source": source, "ticker": ticker})
            c.execute(text("INSERT INTO learning_opportunity_outcomes VALUES(:i,3,'matured',:json)"),
                      {"i": ident, "json": json.dumps({"net_return_pct": ident, "label": "winner", "raw_private": "withheld"})})
    statements = []
    event.listen(db, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    result = recent_visual_context(db, "cfg")
    assert result["available"] and result["displayed_observations"] == 1
    accepted = result["observations"][0]
    assert accepted["input_id"] == 1 and accepted["paper_outcomes"][0]["net_return_pct"] == 11
    assert accepted["paper_outcomes"][0]["paper_only"] is True
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert "raw_private" not in json.dumps(result) and "must not be returned" not in json.dumps(result)
    assert "relative_path" not in json.dumps(result) and "base64" not in json.dumps(result)


def test_no_prospective_match_stays_unknown_and_report_bounds_last_inputs(db):
    for ident in range(1, 17):
        save(db, ident)
    result = recent_visual_context(db, "cfg", limit=999)
    assert result["source_inputs"] == 12 and result["input_limit"] == 12
    assert {item["input_id"] for item in result["observations"]} == set(range(5, 17))
    assert all(item["outcome_status"] == "unavailable" and item["paper_outcomes"] == [] for item in result["observations"])


def test_unbound_manifest_cannot_establish_visual_evidence_for_known_decision_run(db):
    save(db, 1, local=manifest("cfg", None))
    save(db, 2)
    result = recent_visual_context(db, "cfg")
    assert result["available"]
    assert {item["input_id"] for item in result["observations"]} == {2}


def test_paper_outcome_strings_never_forward_image_payload_markers(db):
    save(db, 1)
    with db.begin() as c:
        c.execute(text("INSERT INTO learning_opportunities VALUES(1,'cfg',1,'TSLA')"))
        c.execute(text("INSERT INTO learning_opportunity_outcomes VALUES(1,3,'matured',:json)"), {
            "json": json.dumps({"entry_source": "data:image/png;base64,dGVzdA==",
                                "exit_source": "input_image", "spec_id": "base64",
                                "net_return_pct": 1.5, "label": "winner"})})
    result = recent_visual_context(db, "cfg")
    assert result["available"]
    paper = result["observations"][0]["paper_outcomes"][0]
    assert paper["net_return_pct"] == 1.5 and paper["label"] == "winner"
    assert not {"entry_source", "exit_source", "spec_id"} & paper.keys()
    assert "base64" not in json.dumps(result) and "input_image" not in json.dumps(result)


def test_report_caps_display_at_24_and_discloses_larger_bounded_population(db):
    for ident in range(1, 13):
        values = [observation(image_id=image_id, caveat=caveat)
                  for image_id in ("I01", "I02") for caveat in ("Photo date unknown.", "Reaction unverified.")]
        save(db, ident, local=manifest("cfg", f"run-{ident}", count=2), observations=values)
    result = recent_visual_context(db, "cfg")
    assert result["source_inputs"] == 12 and result["eligible_observations"] == 48
    assert result["displayed_observations"] == 24 and len(result["observations"]) == 24
    assert result["truncated"] is True
    assert {item["input_id"] for item in result["observations"]} == set(range(7, 13))


def test_report_never_echoes_database_diagnostics():
    class Broken:
        def connect(self):
            raise RuntimeError("password=private-value")
    result = recent_visual_context(Broken(), "cfg")
    assert result["available"] is False and "private-value" not in json.dumps(result)
