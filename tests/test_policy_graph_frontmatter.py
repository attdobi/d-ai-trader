"""Strict node-file writer/reader (spec §4.1 / §14 item 9). DB-free."""
from __future__ import annotations

import hashlib

import pytest

from policy_graph import decompose as D
from policy_graph.frontmatter import (
    FrontmatterError, KEY_ORDER, format_scalar, parse_frontmatter_text, parse_inline_map, parse_scalar,
    read_node, read_node_bytes, render_frontmatter, strip_leading_markers, write_node,
)
from policy_graph.model import Node


def _node(**kw) -> Node:
    base = dict(id="DA.directives.strategy.priced_kill", agent="DeciderAgent", title="PRICED KILL", node_type="rule",
                parent="DA.directives.strategy", field="strategy_directives", body="3. PRICED KILL — every BUY",
                sep_before="", sep_after="\n", order=5, polarity="gate", polarity_source="override", owner="db",
                status="active", compiled="stored", locked=False, provenance="prompt_versions#599",
                tags=["priced-kill"], tickers=[])
    base.update(kw)
    return Node(**base)


def _roundtrip(node: Node, tmp_path):
    fm = D.node_to_frontmatter(node, "DeciderAgent.9ea09b9as.v21")
    path = tmp_path / f"{node.id}.md"
    data = write_node(path, fm, node.body)
    assert path.read_bytes() == data
    fm2, body2 = read_node(path)
    back = D.node_from_frontmatter(fm2, body2)
    return fm, data, fm2, back


def test_key_order_and_example_shape(tmp_path):
    node = _node(edges=[{"type": "related_to", "to": "DA.memory.lessons.priced_kill", "via": "#priced-kill"},
                        {"type": "overlaps", "to": "DA.ltm.20", "confidence": 0.61}])
    fm, data, fm2, back = _roundtrip(node, tmp_path)
    text = data.decode("utf-8")
    lines = text.split("\n")
    assert lines[0] == "---"
    assert lines[1] == "id: DA.directives.strategy.priced_kill"
    assert lines[2] == "version: DeciderAgent.9ea09b9as.v21"
    assert 'title: "PRICED KILL"' in lines
    assert "polarity: gate" in lines and "polarity_source: override" in lines
    assert "order: 5" in lines and "locked: false" in lines
    assert 'sep_before: ""' in lines and 'sep_after: "\\n"' in lines
    assert "tags: [priced-kill]" in lines and "tickers: []" in lines
    assert "edges:" in lines
    assert '  - {type: related_to, to: DA.memory.lessons.priced_kill, via: "#priced-kill"}' in lines
    assert "  - {type: overlaps, to: DA.ltm.20, confidence: 0.61}" in lines
    keys = [ln.split(":", 1)[0] for ln in lines[1:lines.index("---", 1)] if not ln.startswith("  -")]
    assert keys == [k for k in KEY_ORDER if k in fm]
    assert text.endswith("\n---\n3. PRICED KILL — every BUY")
    assert fm2["body_sha256"] == hashlib.sha256(node.body.encode()).hexdigest()
    assert back.text == node.text and back.edges == node.edges and back.tags == ["priced-kill"]
    assert back.order == 5 and back.locked is False and back.parent == node.parent


def test_special_values_roundtrip(tmp_path):
    node = _node(title='Colons: and "quotes" — ünïcödé', sep_before="\r\n", sep_after="\t  \n",
                 body="---\nagent: X\n---\n# body starting with a YAML block", provenance="a/b.md@54a50e5e",
                 extra={"inherited_from": "agents/decider/SOUL.default.md", "inherited_git_sha": None,
                        "inherited_resolution": "worktree", "weight": 1.5, "injected": True, "row_created_at": "2026-09-02T14:57:20"})
    fm, data, fm2, back = _roundtrip(node, tmp_path)
    assert back.title == node.title and back.sep_before == "\r\n" and back.sep_after == "\t  \n"
    assert back.body == node.body
    assert back.extra["inherited_git_sha"] is None and back.extra["weight"] == 1.5 and back.extra["injected"] is True
    assert back.extra["inherited_from"] == "agents/decider/SOUL.default.md"
    assert back.extra["row_created_at"] == "2026-09-02T14:57:20"
    assert back.provenance == "a/b.md@54a50e5e"


def test_empty_body_and_null_parent(tmp_path):
    node = _node(id="DA.root", parent=None, field=None, body="", node_type="root", title="root")
    fm, data, fm2, back = _roundtrip(node, tmp_path)
    assert data.endswith(b"\n---\n")
    assert back.body == "" and back.parent is None and back.field is None


def test_numeric_looking_strings_stay_strings(tmp_path):
    node = _node(title="2026", extra={"kind": "12", "ticker": "true"})
    _, _, _, back = _roundtrip(node, tmp_path)
    assert back.title == "2026" and back.extra["kind"] == "12" and back.extra["ticker"] == "true"


def test_scalar_helpers():
    assert format_scalar("") == '""'
    assert format_scalar("plain_bare-value/x#y") == "plain_bare-value/x#y"
    assert format_scalar("with space") == '"with space"'
    assert format_scalar(None) == "null" and format_scalar(True) == "true" and format_scalar(3) == "3"
    assert parse_scalar("null") is None and parse_scalar("true") is True and parse_scalar("3") == 3
    assert parse_scalar('"\\n"') == "\n" and parse_scalar("1.5") == 1.5 and parse_scalar("'q'") == "q"
    assert parse_inline_map('{type: related_to, to: X.y, via: "a, b"}') == {"type": "related_to", "to": "X.y", "via": "a, b"}
    fm = parse_frontmatter_text('id: A.b\ntags: ["x, y", z]\nedges:\n  - {type: cites, to: DA.ticker.IONQ}\nextra: 1')
    assert fm["tags"] == ["x, y", "z"] and fm["edges"] == [{"type": "cites", "to": "DA.ticker.IONQ"}] and fm["extra"] == 1
    assert render_frontmatter({"zzz": 1, "id": "A.b"}).split("\n") == ["id: A.b", "zzz: 1"]


def test_strict_reader_rejects_leading_marker_and_missing_fence():
    with pytest.raises(FrontmatterError):
        read_node_bytes(b"<!-- DA.root.md -->\n---\nid: DA.root\n---\nbody")
    with pytest.raises(FrontmatterError):
        read_node_bytes(b"---\nid: DA.root\nno closing fence")
    with pytest.raises(FrontmatterError):
        parse_frontmatter_text("not a key line")


def test_strip_leading_markers_proposal_path_only():
    assert strip_leading_markers("<!-- DA.root.md -->\n---\nid: DA.root\n---\nx") == "---\nid: DA.root\n---\nx"
    assert strip_leading_markers("---\nid: DA.root\n---\nx") == "---\nid: DA.root\n---\nx"


def test_body_sha_mismatch_raises():
    fm = D.node_to_frontmatter(_node(), "v")
    with pytest.raises(D.NodeIntegrityError):
        D.node_from_frontmatter(fm, "different body")
    assert D.node_from_frontmatter(fm, _node().body).id == "DA.directives.strategy.priced_kill"


def test_first_fence_after_opening_is_the_closing_fence():
    data = b"---\nid: DA.memory\nsep_before: \"\"\n---\n---\nagent: X\n---\nbody"
    fm, body = read_node_bytes(data)
    assert fm["id"] == "DA.memory" and body == "---\nagent: X\n---\nbody"
