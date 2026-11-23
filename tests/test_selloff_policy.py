import json

import pytest

from policy_graph import prompt_audit
from policy_graph.compile import compile_build
from policy_graph.decompose import decompose_row
from policy_graph.code_blocks import code_nodes
from policy_graph.edges import derive_edges
from policy_graph.model import RowMeta
from policy_graph.selloff_policy import add_selloff_fields
from policy_safety import validate_policy_opportunities


def test_selloff_assessment_is_a_citable_node_linked_to_its_existing_gates():
    source = json.loads(prompt_audit.SPEC_PATH.read_text())["agents"]["DeciderAgent"]["fields"]
    updated = add_selloff_fields("DeciderAgent", source)
    assert add_selloff_fields("DeciderAgent", updated) == updated
    validate_policy_opportunities("DeciderAgent", updated)
    build = decompose_row("DeciderAgent", "test", 1, updated,
                          meta=RowMeta(1, None, "operator"), inherited={},
                          code_nodes=code_nodes("DeciderAgent", updated, is_margin_account=False),
                          ltm_nodes=[], is_margin_account=False)
    assert compile_build(build) == updated
    edges = derive_edges(build.nodes, version_stamp="test")
    assert any(e.source == "DA.code.selloff_review" and e.edge_type == "constrains"
               and e.target == "DA.directives.large_selloff_review" for e in edges)
    targets = {e.target for e in edges if e.source == "DA.directives.large_selloff_review"
               and e.edge_type == "related_to"}
    assert {f"DA.directives.strategy.{gate}" for gate in (
        "re_entry_quarantine", "day_chase", "priced_kill")} <= targets


def test_reapplying_protects_later_edits_to_the_same_guideline():
    fields = {"strategy_directives": "## Large selloff review\nLater reviewed wording."}
    with pytest.raises(prompt_audit.AuditConflict):
        add_selloff_fields("DeciderAgent", fields)
