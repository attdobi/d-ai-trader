"""Drift guard for policy_graph.code_blocks — the verbatim copies must equal the prompt literals
in the trader source. The sources are parsed with `ast`, never imported (they import config).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from policy_graph.code_blocks import BLOCKS_BY_ID, CODE_BLOCKS, CODE_SHA, CONSTRAINS, code_nodes
from policy_graph.model import ID_RE, POLARITY_OVERRIDES

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "policy_graph"


# ----------------------------------------------------------------------------- ast helpers
def _render(node):
    """Constant → value; JoinedStr → literal parts with fields rendered as {expr}; else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                out.append("{" + ast.unparse(v.value) + "}")
        return "".join(out)
    return None


def _parse(rel: str) -> ast.AST:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)


def _func(tree: ast.AST, name: str):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"function {name} not found")


def _assign_target(n) -> str:
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        return n.targets[0].id
    return ""


def extract_from_source() -> list:
    """[(id, text)] in CODE_BLOCKS order, read from the trader source with ast."""
    found = {}

    # decider_agent.ask_decision_agent
    ask = _func(_parse("decider_agent.py"), "ask_decision_agent")
    prompt_adds, template_adds = [], []
    for n in ast.walk(ask):
        tgt = _assign_target(n)
        if tgt in ("contrarian_directive", "cash_horizon_block"):
            found[tgt] = _render(n.value)
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and isinstance(n.op, ast.Add):
            text = _render(n.value)
            if text is None:                       # `prompt += "\n\n" + block` style — dynamic, skipped
                continue
            if n.target.id == "prompt":
                prompt_adds.append(text)
            elif n.target.id == "user_prompt_template":
                template_adds.append(text)
    assert len(prompt_adds) == 8, f"expected eight `prompt += (...)` literals, found {len(prompt_adds)}"
    assert len(template_adds) == 1, "expected one `user_prompt_template += ...` literal (JSON fallback)"

    # contrarian_screener
    screener = _parse("contrarian_screener.py")
    for n in ast.walk(_func(screener, "format_index_regime")):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.JoinedStr):
            last = n.value.values[-1]
            if isinstance(last, ast.Constant) and "# DEPLOYMENT RULE BY REGIME" in last.value:
                s = last.value
                found["index_regime"] = s[s.index("# DEPLOYMENT RULE BY REGIME"):]
    for n in ast.walk(_func(screener, "format_contrarian_watchlist")):
        if _assign_target(n) == "lines" and isinstance(n.value, ast.List):
            found["watchlist_header"] = "\n".join(e.value for e in n.value.elts)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
                and n.args and isinstance(n.args[0], ast.BinOp) and isinstance(n.args[0].left, ast.Constant)
                and str(n.args[0].left.value).startswith("# QUARANTINE")):
            found["quarantine_line"] = n.args[0].left.value

    # decider_memory
    mem = _parse("decider_memory.py")
    for n in ast.walk(_func(mem, "format_long_term_memory")):
        if _assign_target(n) == "lines" and isinstance(n.value, ast.List):
            found["lessons_header"] = n.value.elts[0].value
    for n in ast.walk(_func(mem, "build_working_memory")):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.BinOp) and isinstance(n.value.left, ast.Constant):
            found["recent_activity_header"] = n.value.left.value

    # main.get_openai_summary
    for n in ast.walk(_func(_parse("main.py"), "get_openai_summary")):
        if _assign_target(n) == "feedback_context":
            text = _render(n.value)
            if text and "PERFORMANCE FEEDBACK" in text:
                found["feedback_suffix"] = text

    # feedback_agent._generate_ai_feedback (the FEEDBACK_* locals; the fallback method has its own copies)
    for n in ast.walk(_func(_parse("feedback_agent.py"), "_generate_ai_feedback")):
        tgt = _assign_target(n)
        if tgt.startswith("FEEDBACK_"):
            found[tgt] = _render(n.value)

    ordered = [
        ("DA.code.crowd_fade", found["contrarian_directive"]),
        ("DA.code.cash_playbook", found["cash_horizon_block"]),
        ("DA.code.index_regime", found["index_regime"]),
        ("DA.code.watchlist_header", found["watchlist_header"]),
        ("DA.code.quarantine_line", found["quarantine_line"]),
        ("DA.code.lessons_header", found["lessons_header"]),
        ("DA.code.recent_activity_header", found["recent_activity_header"]),
        ("DA.code.cash_disclosure", prompt_adds[0]),
        ("DA.code.justification_detail", prompt_adds[1]),
        ("DA.code.considered_setups", prompt_adds[2]),
        ("DA.code.data_availability", prompt_adds[3]),
        ("DA.code.deploy_policy", prompt_adds[4]),
        ("DA.code.confirmation_policy", prompt_adds[5]),
        ("DA.code.recency_provenance", prompt_adds[6]),
        ("DA.code.guideline_citations", prompt_adds[7]),
        ("DA.code.json_fallback", template_adds[0]),
        ("SA.code.feedback_suffix", found["feedback_suffix"]),
        ("FA.code.system_base", found["FEEDBACK_SYSTEM_BASE"]),
        ("FA.code.base_instructions", found["FEEDBACK_BASE_INSTRUCTIONS"]),
        ("FA.code.json_format", found["FEEDBACK_JSON_FORMAT"]),
    ]
    return ordered


# ----------------------------------------------------------------------------- drift guard
def test_code_blocks_match_source_verbatim():
    expected = extract_from_source()
    actual = [(b.id, b.text) for b in CODE_BLOCKS]
    assert [i for i, _ in actual] == [i for i, _ in expected], "CODE_BLOCKS id order drifted"
    for (bid, exp), (_, act) in zip(expected, actual):
        assert act == exp, f"{bid}: verbatim copy in policy_graph/code_blocks.py drifted from the source literal"


def test_code_blocks_metadata_is_well_formed():
    ids = [b.id for b in CODE_BLOCKS]
    assert len(ids) == len(set(ids)) == 20
    for b in CODE_BLOCKS:
        assert ID_RE.match(b.id) and b.id.split(".")[1] == "code"
        assert b.text and b.title
        assert (ROOT / b.source_file).exists(), b.source_file
        assert b.position in {"user_template_tail", "user_prompt_dynamic", "user_prompt_tail",
                              "system_tail", "system_base", "user_prompt_head"}
        assert b.id.split(".", 1)[1] in POLARITY_OVERRIDES, f"{b.id} needs a polarity override in model.py"
    assert re.fullmatch(r"[0-9a-f]{12}", CODE_SHA)
    assert set(CONSTRAINS) == {"DA.code.index_regime", "DA.code.watchlist_header", "DA.code.quarantine_line",
                               "DA.code.deploy_policy", "DA.code.confirmation_policy"}
    assert CONSTRAINS["DA.code.confirmation_policy"] == ["regime_gate", "extension_cap", "re_entry_quarantine", "priced_kill"]
    assert CONSTRAINS["DA.code.index_regime"] == ["regime_gate"]
    assert CONSTRAINS["DA.code.quarantine_line"] == ["re_entry_quarantine"]


def test_fstring_fields_are_left_as_placeholders():
    assert "${settled_cash_value}" in BLOCKS_BY_ID["DA.code.cash_disclosure"].text
    assert "${MIN_BUY_AMOUNT}" in BLOCKS_BY_ID["DA.code.cash_disclosure"].text
    assert "{supplied_fields}" in BLOCKS_BY_ID["FA.code.base_instructions"].text
    assert "{summarizer_feedback}" in BLOCKS_BY_ID["SA.code.feedback_suffix"].text
    # the JSON fallback keeps its .format() escapes
    assert "{{" in BLOCKS_BY_ID["DA.code.json_fallback"].text


# ----------------------------------------------------------------------------- code_nodes
def _v21_fields() -> dict:
    return {
        "system_prompt": (FIXTURES / "decider_v21_system.md").read_bytes().decode("utf-8"),
        "user_prompt_template": (FIXTURES / "decider_v21_user.md").read_bytes().decode("utf-8"),
        "strategy_directives": (FIXTURES / "decider_v21_sd.md").read_bytes().decode("utf-8"),
        "soul": (FIXTURES / "decider_v21_soul.md").read_bytes().decode("utf-8"),
        "memory": (FIXTURES / "decider_v21_memory.md").read_bytes().decode("utf-8"),
    }


def test_code_nodes_fire_on_v21():
    nodes = code_nodes("DeciderAgent", _v21_fields(), is_margin_account=False)
    by_id = {n.id: n for n in nodes}
    assert set(by_id) == {b.id for b in CODE_BLOCKS if b.id.startswith("DA.")}
    assert by_id["DA.code.crowd_fade"].extra["fires"] is True
    assert by_id["DA.code.cash_playbook"].extra["fires"] is True
    assert by_id["DA.code.json_fallback"].extra["fires"] is False        # v21 template contains "JSON"
    assert by_id["DA.code.json_fallback"].status == "inactive"
    assert by_id["DA.code.crowd_fade"].status == "read-only"
    for n in nodes:
        assert n.owner == "code" and n.compiled == "never" and n.locked is True
        assert n.parent == "DA.code" and n.node_type == "code" and n.field is None
        assert n.body == BLOCKS_BY_ID[n.id].text
        assert n.extra["code_sha"] == CODE_SHA
        assert n.extra["source_file"] == BLOCKS_BY_ID[n.id].source_file
        assert n.extra["position"] == BLOCKS_BY_ID[n.id].position
        assert n.polarity_source == "override"
    assert [n.order for n in nodes] == list(range(len(nodes)))
    assert by_id["DA.code.crowd_fade"].provenance == "decider_agent.py:ask_decision_agent"


def test_code_nodes_conditions():
    fields = _v21_fields()
    fields["user_prompt_template"] += "\n\n🚫 CROWD-FADE AWARENESS already here"
    by_id = {n.id: n for n in code_nodes("DeciderAgent", fields, is_margin_account=False)}
    assert by_id["DA.code.crowd_fade"].extra["fires"] is False
    # directive text carrying CROWD-FADE also suppresses it
    fields = _v21_fields()
    fields["strategy_directives"] += "\nCROWD-FADE lens applies."
    by_id = {n.id: n for n in code_nodes("DeciderAgent", fields, is_margin_account=False)}
    assert by_id["DA.code.crowd_fade"].extra["fires"] is False
    # margin accounts never get the cash playbook
    by_id = {n.id: n for n in code_nodes("DeciderAgent", _v21_fields(), is_margin_account=True)}
    assert by_id["DA.code.cash_playbook"].extra["fires"] is False
    # a template without JSON gets the fallback
    fields = _v21_fields()
    fields["user_prompt_template"] = "Decide now."
    by_id = {n.id: n for n in code_nodes("DeciderAgent", fields, is_margin_account=False)}
    assert by_id["DA.code.json_fallback"].extra["fires"] is True
    # None fields are tolerated
    by_id = {n.id: n for n in code_nodes("DeciderAgent", {k: None for k in fields}, is_margin_account=False)}
    assert by_id["DA.code.json_fallback"].extra["fires"] is True


@pytest.mark.parametrize("agent,prefix,count", [("SummarizerAgent", "SA", 1), ("FeedbackAgent", "FA", 3)])
def test_code_nodes_other_agents(agent, prefix, count):
    nodes = code_nodes(agent, {}, is_margin_account=False)
    assert len(nodes) == count
    assert all(n.id.startswith(prefix + ".code.") and n.parent == f"{prefix}.code" for n in nodes)
    assert all(n.extra["fires"] is True for n in nodes)
