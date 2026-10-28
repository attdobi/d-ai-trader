"""Market labels are auditable browsing aids, never a learned trading boundary."""
from copy import deepcopy

import pytest

from policy_graph import themes as T


def landmark(body="Keep the active priced stop.", version=1, **extra):
    return {"id": "DA.rule", "key": f"DA.rule:rev{version}", "body": body,
            "versions": [version], "x": .123, "y": .456, **extra}


def case(reason="", ticker="AAA", version=1, **extra):
    return {"id": "c1", "input_id": 5, "run_id": "r1", "ticker": ticker,
            "prompt_version": version, "reason": reason, "cited": ["DA.rule"],
            "action": "BUY", "outcomes": {}, **extra}


def catalog(rows):
    return {row["id"]: row for row in rows}


def test_topic_words_are_multilabel_and_match_literal_evidence():
    found = T.matches("Iran war threatens Hormuz crude oil. AI cloud demand raises DRAM/HBM chip production.")
    assert set(found) == {"geopolitics_iran", "energy_oil", "technology", "ai", "semiconductors", "memory_manufacturing"}
    assert found["energy_oil"] == ["crude", "oil"]
    assert found["memory_manufacturing"] == ["dram", "hbm"]


@pytest.mark.parametrize("body", [
    "# Agent MEMORY\nLearn from historical trades and retain current rules.",
    "Consider EV/EBITDA enterprise value before judging valuation.",
    "A price war and a bidding war are not military conflict.",
    "The claimant said it was fair; neither word establishes a market theme.",
    "Separate fact from inference while computing risk and compute transaction cost.",
    "Generative outputs are uncertain; a model's inference does not establish causality.",
])
def test_generic_policy_and_ambiguous_substrings_do_not_invent_market_events(body):
    assert T.matches(body) == {}


def test_issuer_reference_is_exposure_not_iran_or_a_reported_catalyst():
    cases = [case(ticker="XOM"), case(ticker="GM", input_id=6), case(ticker="MU", input_id=7)]
    cat, method = T.annotate([], [cases])
    assert cases[0]["market_themes"] == ["energy_oil"]
    assert "geopolitics_iran" not in {topic for row in cases for topic in row["market_themes"]}
    assert cases[1]["market_themes"] == ["electric_vehicles"]
    assert "memory_manufacturing" in cases[2]["market_themes"]
    assert all(entry["source"] == "ticker_reference" and "not evidence" in entry["note"]
               for row in cases for entry in row["theme_evidence"])
    assert method["issuer_reference_id"] == T.ISSUER_REFERENCE_ID
    assert catalog(cat)["geopolitics_iran"]["case_count"] == 0


def test_unknown_ticker_has_no_guessed_company_or_event_and_generic_body_stays_general():
    nodes, cases = [landmark()], [case(ticker="UNSEEN")]
    cat, method = T.annotate(nodes, [cases])
    assert cases[0]["market_themes"] == nodes[0]["market_themes"] == ["general"]
    assert nodes[0]["direct_market_themes"] == nodes[0]["linked_market_themes"] == []
    assert nodes[0]["theme_evidence"] == []
    assert catalog(cat)["general"]["case_count"] == 1
    assert "not quality-rate denominators" in method["counts_scope"]
    assert "decision boundary" in method["note"]


def test_case_associations_attach_only_to_the_exact_cited_policy_revision():
    nodes = [landmark(version=1), landmark(version=2)]
    observed = case("Iran conflict and oil-price uncertainty.", version=1)
    T.annotate(nodes, [[observed]])
    first, second = nodes
    assert first["market_themes"] == ["geopolitics_iran", "energy_oil"]
    assert first["direct_market_themes"] == []
    assert all(entry["source"] == "cited_case" and entry["case_ids"] == ["c1"] for entry in first["theme_evidence"])
    assert second["market_themes"] == ["general"]
    assert second["theme_evidence"] == []


@pytest.mark.parametrize("version", [None, "unknown", True])
def test_case_without_a_known_valid_version_cannot_assign_a_revision_theme(version):
    nodes = [landmark()]
    T.annotate(nodes, [[case("Oil supply", version=version)]])
    assert nodes[0]["market_themes"] == ["general"]


def test_direct_rule_text_and_cited_case_provenance_remain_distinct():
    nodes = [landmark("Control AI-infrastructure and semiconductor correlation.")]
    T.annotate(nodes, [[case("A verified electric vehicle demand report.")]])
    node = nodes[0]
    assert "ai" in node["direct_market_themes"]
    assert "electric_vehicles" in node["linked_market_themes"]
    assert next(e for e in node["theme_evidence"] if e["theme_id"] == "ai")["source"] == "direct_text"
    assert next(e for e in node["theme_evidence"] if e["theme_id"] == "electric_vehicles")["source"] == "cited_case"


def test_annotations_never_rewrite_text_coordinates_actions_outcomes_or_coverage():
    nodes = [landmark("AI entry rule.")]
    observed = case("Oil headline.", outcomes={"3": {"status": "matured", "net_return_pct": -2}},
                    coverage="historical_decision_log", eligible_for_recall=False)
    old_node, old_case = deepcopy(nodes[0]), deepcopy(observed)
    T.annotate(nodes, [[observed]])
    assert {key: nodes[0][key] for key in old_node} == old_node
    assert {key: observed[key] for key in old_case} == old_case


def test_duplicate_display_rows_merge_themes_without_doubling_counts_or_replacing_actions():
    prospective = case("", action="PASS", outcomes={"3": {"status": "matured"}})
    audit = case("Iran and oil", action="BUY", id="audit-1")
    nodes = [landmark()]
    cat, _ = T.annotate(nodes, [[prospective], [audit]])
    assert prospective["market_themes"] == audit["market_themes"] == ["geopolitics_iran", "energy_oil"]
    assert prospective["action"] == "PASS" and audit["action"] == "BUY"
    for topic in ("geopolitics_iran", "energy_oil"):
        item = catalog(cat)[topic]
        assert item["case_count"] == item["assessed_count"] == item["matured_count"] == 1
        assert item["direct_landmark_count"] == 0 and item["linked_landmark_count"] == 1
    assert nodes[0]["theme_evidence"][0]["case_count"] == 1


def test_dedupe_does_not_collide_a_run_string_with_an_input_id():
    first = case("Oil", input_id=5)
    second = case("Oil", input_id=None, run_id="5", id="other")
    cat, _ = T.annotate([], [[first, second]])
    assert catalog(cat)["energy_oil"]["case_count"] == 2


def test_cross_config_case_cannot_influence_catalog_or_cited_rule():
    wrong = case("Iran oil event", config_hash="other")
    right = case("", config_hash="cfg", input_id=8)
    nodes = [landmark()]
    cat, _ = T.annotate(nodes, [[wrong, right]], config_hash="cfg")
    assert "market_themes" not in wrong
    assert nodes[0]["market_themes"] == ["general"]
    assert catalog(cat)["geopolitics_iran"]["case_count"] == 0


def test_titles_identifiers_and_outcomes_do_not_create_direct_market_labels():
    nodes = [landmark(title="Iran war", id="DA.memory.iran")]
    observed = case("", outcomes={"3": {"status": "matured", "why": "Iran oil"}})
    T.annotate(nodes, [[observed]])
    assert nodes[0]["market_themes"] == observed["market_themes"] == ["general"]


def test_early_annotations_do_not_acquire_later_case_versions():
    nodes = [landmark(version=1), landmark(version=2), landmark(version=3)]
    T.annotate(nodes, [[case("AI data center", version=2)]])
    assert [node["market_themes"] for node in nodes] == [["general"], ["technology", "ai"], ["general"]]
