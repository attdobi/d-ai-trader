"""The visual supplement preserves existing controls and compilation contracts."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re

import pytest

from policy_graph.compile import compile_build
from policy_graph.decompose import decompose_row
from policy_graph.model import FIELDS, RowMeta
from policy_graph.visual_policy import HEADING, add_visual_fields
from policy_safety import validate_policy_opportunities

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "policy_graph/audited_agent_prompts.json").read_text())["agents"]


@pytest.mark.parametrize("agent", list(SOURCE))
def test_append_preserves_existing_text_placeholders_and_company_contract(agent):
    fields = deepcopy(SOURCE[agent]["fields"])
    before = deepcopy(fields)
    after = add_visual_fields(agent, fields)
    assert fields == before and after is not fields
    for field in FIELDS:
        assert after[field].startswith(before[field])
        placeholders = lambda value: set(re.findall(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})", value))
        assert placeholders(after[field]) == placeholders(before[field])
    if agent == "CompanyExtractionAgent":
        assert after == before
    else:
        assert after != before
    assert add_visual_fields(agent, after) == after
    validate_policy_opportunities(agent, after)


@pytest.mark.parametrize("agent", ["SummarizerAgent", "DeciderAgent", "FeedbackAgent"])
def test_added_sections_roundtrip_without_changing_existing_trading_rule_bodies(agent):
    before = SOURCE[agent]["fields"]
    after = add_visual_fields(agent, before)
    def build(fields):
        return decompose_row(agent, "fixture", 1, fields,
            meta=RowMeta(1, datetime(2026, 10, 29), "operator"),
            inherited={}, code_nodes=[], ltm_nodes=[], is_margin_account=False)
    old = build(before)
    new = build(after)
    assert compile_build(new) == after
    old_rules = {n.id: n.body for n in old.nodes if n.node_type == "rule"}
    new_rules = {n.id: n.body for n in new.nodes if n.node_type == "rule"}
    assert all(new_rules[ident] == body for ident, body in old_rules.items())


def test_summarizer_preserves_schema_and_places_visible_observations_in_consumed_insights():
    after = add_visual_fields("SummarizerAgent", SOURCE["SummarizerAgent"]["fields"])
    supplement = after["system_prompt"].split(HEADING)[-1]
    assert "VISUAL FRAMING:" in supplement and "within the existing insights word budget" in supplement
    assert "visual_context" not in supplement
    assert "caption" in supplement and "interpretation" in supplement and "untrusted" in supplement


def test_decider_optional_research_schema_never_grants_trade_permission_or_identity_claims():
    after = add_visual_fields("DeciderAgent", SOURCE["DeciderAgent"]["fields"])
    supplement = after["system_prompt"].split(HEADING)[-1]
    assert '"image_id":"I01"' in supplement
    assert "top-level visual_context array" in supplement and "empty or omitted" in supplement
    assert "actual emotion" in supplement and "do not identify" in supplement
    assert "Visual tone alone never authorizes" in supplement
    assert "not a current executable quote" in supplement
    assert "at most two observations per image" in supplement and "at most 24" in supplement


def test_weekly_feedback_receives_live_soul_hypothesis_and_no_auto_promotion_rules():
    after = add_visual_fields("FeedbackAgent", SOURCE["FeedbackAgent"]["fields"])
    supplement = after["soul"].split(HEADING)[-1]
    assert "No change is valid" in supplement and "never auto-activate" in supplement
    assert "same eligible cases" in supplement and "later independent periods" in supplement
    assert "not direct inspection" in supplement and "not intent" in supplement


@pytest.mark.parametrize("tail", ["", "\n", "\n\n", "  \n"])
def test_append_keeps_original_trailing_bytes_and_is_idempotent(tail):
    fields = {field: "Original {content}" + tail for field in FIELDS}
    updated = add_visual_fields("SummarizerAgent", fields)
    assert updated["system_prompt"].startswith(fields["system_prompt"])
    assert updated == add_visual_fields("SummarizerAgent", updated)


def test_unknown_agent_or_nontext_field_fails_before_transforming():
    with pytest.raises(ValueError):
        add_visual_fields("DeciderAgnt", {})
    with pytest.raises(TypeError):
        add_visual_fields("DeciderAgent", {"soul": {"instruction": "wrong type"}})
