"""Proposal style warnings reach the Policy Graph tab: the API attaches each style_check warning to its
file card with a plain-language sentence (read-time, so warnings stored on older proposals render too),
and policy-graph.js renders them per file as a caution."""
from __future__ import annotations

from pathlib import Path

from policy_graph import proposals as P

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plain_style_warning_sentences():
    assert P.plain_style_warning("gate is 348 characters; plain gates stay under 240") == \
        "Gate is 348 characters; the target is 240."
    assert P.plain_style_warning("lesson is 301 characters; plain gates stay under 240") == \
        "Lesson is 301 characters; the target is 240."
    assert P.plain_style_warning("gate tests 3 conditions; one condition per gate — split it") == \
        "Gate tests 3 conditions at once; a gate should test one, so split it."
    assert P.plain_style_warning("lesson has 2 parenthetical asides; move the numbers into the sentence") == \
        "Lesson has 2 asides in parentheses; put the numbers in the sentence itself."
    assert P.plain_style_warning("primary gate has no 'Falsified if …' metric in its text").startswith(
        "The primary gate never says how to tell it failed")
    assert P.plain_style_warning("something new") == "Something new."
    assert P.plain_style_warning("") == "" and P.plain_style_warning(None) == ""


def test_every_style_check_warning_has_a_plain_sentence():
    dense = P.FileChange(id="DA.directives.strategy.x", action="add", primary=True, body=(
        "9. EVENT GATE — read the block (every cycle). IF a THEN b. IF c THEN d (see above). " + "x" * 260))
    lesson = P.FileChange(id="DA.memory.lessons.z", action="add", body="- **#tag — short.** (an aside) (another) " + "y" * 300)
    warnings = P.style_check([dense, lesson])
    assert len(warnings) == 6
    for w in warnings:
        plain = P.plain_style_warning(w["warning"])
        assert plain[0].isupper() and plain.endswith(".")
        assert plain != w["warning"][0].upper() + w["warning"][1:] + "."    # a known pattern, not passthrough


def test_public_attaches_warnings_to_their_file_card():
    row = {
        "id": 14, "status": "review", "agent_type": "DeciderAgent", "base_version": 40,
        "patch": {
            "reasoning": "r",
            "files": [{"id": "DA.directives.strategy.day_chase", "action": "edit"},
                      {"id": "DA.memory.lessons.new", "proposed_id": "DA.memory.lessons.drafted", "action": "add"},
                      {"id": "DA.soul.risk", "action": "edit"}],
            "style": [{"id": "DA.directives.strategy.day_chase",
                       "warning": "gate is 315 characters; plain gates stay under 240"},
                      {"id": "DA.memory.lessons.drafted",
                       "warning": "lesson has 2 parenthetical asides; move the numbers into the sentence"}],
        },
    }
    out = P._public(row)
    by_id = {f["id"]: f for f in out["files"]}
    assert by_id["DA.directives.strategy.day_chase"]["style"] == [{
        "id": "DA.directives.strategy.day_chase", "warning": "gate is 315 characters; plain gates stay under 240",
        "plain": "Gate is 315 characters; the target is 240."}]
    assert [w["plain"] for w in by_id["DA.memory.lessons.new"]["style"]] == [
        "Lesson has 2 asides in parentheses; put the numbers in the sentence itself."]
    assert by_id["DA.soul.risk"]["style"] == []
    assert [w["plain"] for w in out["style"]][0] == "Gate is 315 characters; the target is 240."
    # a proposal stored before the lint existed has no style list at all
    bare = P._public({**row, "patch": {"files": [{"id": "DA.x", "action": "edit"}]}})
    assert bare["style"] == [] and bare["files"][0]["style"] == []


def test_policy_graph_js_renders_style_warnings_per_file():
    js = (REPO_ROOT / "static" / "js" / "policy-graph.js").read_text(encoding="utf-8")
    assert "function styleWarningsHtml(" in js
    assert "styleWarningsHtml(fileStyleWarnings(p, f), 'Style check')" in js     # inside fileCardHtml
    assert "w.plain || w.warning" in js
    card = js[js.index("function fileCardHtml("):js.index("function proposalCardHtml(")]
    assert "fileStyleWarnings(p, f)" in card
    html = (REPO_ROOT / "templates" / "policy_graph.html").read_text(encoding="utf-8")
    assert ".pg-file-style {" in html and "var(--warning)" in html.split(".pg-file-style {", 1)[1].split("}", 1)[0]
