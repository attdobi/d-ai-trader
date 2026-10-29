"""Atlas facets add useful labels without fabricating events or moving points."""
from copy import deepcopy
import json

import pytest

from policy_graph.atlas_taxonomy import annotate_atlas_points, atlas_catalog, VERSION
from policy_graph.taxonomy import HIERARCHY, VERSION as MARKET_VERSION


def guideline(ident, title, body, field="strategy_directives"):
    return {"id":ident,"key":ident+":revision1","kind":"guideline","title":title,
            "body":body,"field":field,"x":.24,"y":.81,"market_themes":["general"],"versions":[59,60]}


@pytest.mark.parametrize("title,body,family",[
    ("Regime gate","Read regime before evaluating entries.","policy_entries"),
    ("Priced kill","Sell a holding when its price crosses the stop.","policy_risk"),
    ("Correlation","Apply the current portfolio exposure limits.","policy_capital"),
    ("Earnings candidate","Own-company release must have verified future timing.","policy_events"),
    ("Ground truth","Supplied portfolio records establish ownership.","policy_evidence"),
    ("Latest feedback reminder","Review independent outcomes before changing policy.","policy_learning"),
    ("Core philosophy","Use an evidence-grounded decision style.","policy_identity"),
])
def test_policy_capabilities_separate_general_rules_into_inspectable_roles(title,body,family):
    original=guideline("DA.rule",title,body)
    value=annotate_atlas_points([original])[0]
    assert value["family_id"]==family
    assert value["atlas_assignment"]["facet"]=="policy_capability"
    assert value["atlas_assignment"]["matched_terms"]
    assert value["atlas_facets"]["market_topics"]==["general"]


def test_policy_has_both_facets_but_news_does_not_become_a_control_rule():
    rule=guideline("DA.rule","Event exposure","Review Iran-related exposure with current limits.")
    news={"kind":"news_observation","key":"summary:1","text":"Iran risk headlines discuss crude oil.\nData availability and stop rules are not shown.",
          "market_themes":["geopolitics","geopolitics_iran","energy","energy_oil"],"x":.3,"y":.4}
    values=annotate_atlas_points([rule,news])
    assert values[0]["atlas_assignment"]["facet"]=="policy_capability"
    assert "geopolitics_iran" in values[0]["atlas_facets"]["market_topics"]
    assert "general" not in values[0]["atlas_facets"]["market_topics"]
    assert values[1]["family_id"]=="market_geopolitics"
    assert values[1]["atlas_facets"]["policy_capabilities"]==[]


def test_specific_headline_beats_incidental_market_metadata():
    news={"kind":"news_observation","text":"[MU] Memory manufacturing demand rises.\n[MSFT] AI infrastructure investment reported.\n[AMD] New chips launch.\nIran and oil are mentioned in broader context. EVENT CALENDAR: CPI not_shown.",
          "market_themes":["geopolitics_iran","energy_oil","technology","semiconductors","memory_manufacturing"]}
    value=annotate_atlas_points([news])[0]
    assert value["family_id"]=="market_compute"
    assert value["atlas_assignment"]["basis"]=="headline_terms"
    assert "memory manufacturing" in value["atlas_assignment"]["matched_terms"]


def test_macro_family_requires_headline_context_and_missing_scaffold_does_not_supply_event():
    values=annotate_atlas_points([
        {"kind":"news_observation","text":"EVENT CALENDAR: FOMC not_shown; CPI not_shown; jobs report not_shown."},
        {"kind":"news_observation","text":"Federal Reserve holds interest rates as inflation eases."},
        {"kind":"news_observation","text":"[ABC] Revenue rises after quarterly results."},
        {"kind":"news_observation","text":"Risk-off; no current market tape shown. EVENT CALENDAR: FOMC not_shown; CPI not_shown; jobs report not_shown."},
    ])
    assert [v["family_id"] for v in values]==["market_other","market_macro","market_corporate","market_other"]
    assert values[1]["atlas_facets"]["market_topics"]==["general"]
    assert values[1]["atlas_assignment"]["canonical_topic_id"] is None


def test_feedback_without_a_market_subject_is_learning_research_not_approved_guideline():
    source={"kind":"feedback_hypothesis","text":"Review the matched cohort before proposing a policy change."}
    value=annotate_atlas_points([source])[0]
    assert value["kind"]=="feedback_hypothesis" and value["family_id"]=="policy_learning"
    assert value["atlas_assignment"]["basis"]=="source_kind_feedback"


def test_annotations_preserve_coordinates_revision_identity_and_inputs_exactly():
    points=[guideline("DA.stop","Priced kill","Keep a numeric stop."),
            {"kind":"news_observation","key":"summary:7","text":"Hormuz closure is denied.","x":None,"y":None,"market_themes":["shipping_hormuz"]}]
    before=deepcopy(points)
    values=annotate_atlas_points(points)
    assert points==before
    for old,new in zip(points,values):
        assert all(new[key]==value for key,value in old.items())
        assert new["atlas_taxonomy_version"]==VERSION
        assert new["atlas_assignment"]["coordinates_unchanged"]
    assert values[1]["family_id"]=="market_geopolitics"
    assert values[1]["atlas_facets"]["market_paths"][-1]["path_label"]=="Trade / shipping / Strait of Hormuz"


def test_catalog_retains_all_market_identifiers_and_is_independent_of_caller_edits():
    catalog=atlas_catalog()
    assert catalog["market_taxonomy_version"]==MARKET_VERSION
    assert {t["id"] for t in catalog["market_topics"]}==set(HIERARCHY)
    assert {f["facet"] for f in catalog["families"]}=={"market_topic","policy_capability"}
    catalog["families"][0]["label"]="mutated"
    assert atlas_catalog()["families"][0]["label"]=="Entries & setups"
    assert "causal" in atlas_catalog()["note"]


@pytest.mark.parametrize("field,family",[("soul","policy_identity"),("memory","policy_learning"),("strategy_directives","policy_entries"),(None,"policy_evidence")])
def test_unknown_policy_text_uses_explicit_field_fallback_without_a_market_claim(field,family):
    value=annotate_atlas_points([{"id":"DA.opaque","body":"A short opaque sentence.","field":field}])[0]
    assert value["family_id"]==family and value["atlas_assignment"]["basis"]=="field_fallback"
    assert value["atlas_facets"]["market_topics"]==["general"]


def test_bad_point_shape_is_rejected_instead_of_silently_losing_identity():
    with pytest.raises(TypeError):
        annotate_atlas_points([None])


def test_identifier_heading_fallback_is_named_as_identifier_evidence():
    value=annotate_atlas_points([{"id":"DA.directives.priced_kill","body":"Use the supplied numeric level."}])[0]
    assert value["family_id"]=="policy_risk"
    assert value["atlas_assignment"]["basis"]=="identifier_terms"
