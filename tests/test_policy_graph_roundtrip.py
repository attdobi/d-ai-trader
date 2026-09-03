"""Policy graph fidelity: compile(decompose(text)) == text byte-for-byte (spec §14 item 1).

DB-free. Every fixture in tests/fixtures/policy_graph round-trips through
decompose_row → node_to_frontmatter/write_node → read_node/node_from_frontmatter → compile_stored,
plus synthetic edge cases, a 500-case seeded random-composition test, the partition invariant,
corrupted-body detection and stored_null → None.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from policy_graph import decompose as D
from policy_graph import compile as C
from policy_graph.frontmatter import read_node, write_node
from policy_graph.model import COMPILED_FIELDS, FIELDS, InheritedText, RowMeta, Slice, version_stamp

FX = Path(__file__).parent / "fixtures" / "policy_graph"
INDEX = json.loads((FX / "INDEX.json").read_text(encoding="utf-8"))
CFG = "cfg_test"


def fixture_text(name: str) -> str:
    return (FX / name).read_bytes().decode("utf-8")


def meta_for(entry: dict | None = None) -> RowMeta:
    entry = entry or {}
    return RowMeta(
        prompt_version_id=entry.get("prompt_version_id", 1),
        created_at=datetime(2026, 9, 2, 14, 57, 20),
        created_by=entry.get("created_by", "prompt_lab"),
        description=entry.get("description", ""),
        is_active=False,
    )


def build_for(agent_type: str, version: int, fields: dict, *, inherited=None, meta=None):
    return D.decompose_row(agent_type, CFG, version, fields, meta=meta or meta_for(), inherited=inherited or {},
                           code_nodes=[], ltm_nodes=[], is_margin_account=False)


def write_version_dir(tmp: Path, agent_type: str, version: int, build) -> Path:
    """Minimal stand-in for store.materialize: node files + manifest.json (no edges)."""
    vdir = tmp / f"v{version}"
    vdir.mkdir(parents=True, exist_ok=True)
    stamp = version_stamp(agent_type, CFG, version)
    for node in build.nodes:
        write_node(vdir / f"{node.id}.md", D.node_to_frontmatter(node, stamp), node.body)
    manifest = {
        "schema": 1, "agent_type": agent_type, "prefix": build.root_id.split(".")[0], "config_hash": CFG,
        "version": version, "root_id": build.root_id, "fields": build.fields_meta,
        "compile_order": build.compile_order,
    }
    (vdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return vdir


def roundtrip(tmp: Path, agent_type: str, fields: dict, version: int = 1, **kw) -> dict:
    build = build_for(agent_type, version, fields, **kw)
    # in-memory compile agrees with the input
    mem = C.compile_build(build)
    for f in FIELDS:
        assert mem[f] == fields.get(f), f"compile_build mismatch for {f}"
    vdir = write_version_dir(tmp, agent_type, version, build)
    ver = C.read_version_dir(vdir)
    stored = C.compile_stored(ver)
    for f in FIELDS:
        expected = fields.get(f)
        if expected is None:
            assert stored[f] is None
        else:
            assert stored[f].encode("utf-8") == expected.encode("utf-8"), f"round-trip mismatch for {f}"
    return {"build": build, "version": ver, "stored": stored, "dir": vdir}


def assert_partition(field: str, text: str) -> list:
    slices = D.slice_field(field, text)
    assert slices[0].start == 0 and slices[-1].end == len(text)
    for a, b in zip(slices, slices[1:]):
        assert a.end == b.start
        assert b.end >= b.start
    assert "".join(text[s.start:s.end] for s in slices) == text
    return slices


# ----------------------------------------------------------------------------- fixtures
@pytest.mark.parametrize("entry", INDEX, ids=[e["file"] for e in INDEX])
def test_fixture_roundtrip(tmp_path, entry):
    text = fixture_text(entry["file"])
    assert not text.endswith("\n"), "fixtures are captured without a trailing newline"
    fields = {f: None for f in FIELDS}
    fields[entry["field"]] = text
    res = roundtrip(tmp_path, entry["agent_type"], fields, version=entry["version"], meta=meta_for(entry))
    assert_partition(entry["field"], text)
    # the last slice of every stored field has sep_after == ""
    build = res["build"]
    last = build.compile_order[entry["field"]][-1]
    node = next(n for n in build.nodes if n.id == last)
    assert node.sep_after == ""
    # every db node's frontmatter carries a matching sha
    for p in res["dir"].glob("*.md"):
        fm, body = read_node(p)
        assert fm["body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()


def test_all_fixture_fields_of_one_version_together(tmp_path):
    fields = {
        "system_prompt": fixture_text("decider_v21_system.md"),
        "user_prompt_template": fixture_text("decider_v21_user.md"),
        "strategy_directives": fixture_text("decider_v21_sd.md"),
        "soul": fixture_text("decider_v21_soul.md"),
        "memory": fixture_text("decider_v21_memory.md"),
    }
    res = roundtrip(tmp_path, "DeciderAgent", fields, version=21)
    build = res["build"]
    ids = [n.id for n in build.nodes]
    assert len(ids) == len(set(ids))
    assert build.compile_order["system_prompt"] == ["DA.template.system"]
    assert build.compile_order["user_prompt_template"] == ["DA.template.user"]
    assert build.compile_order["strategy_directives"][0] == "DA.directives"


# ----------------------------------------------------------------------------- synthetic edge cases
SYNTHETIC = {
    "empty": "",
    "newline": "\n",
    "whitespace_only": " \t\n\n  ",
    "hr_only": "\n\n---\n",
    "crlf": "## A\r\n- x\r\n",
    "crlf_rules": "## Rules\r\n1. FIRST — a\r\n2. SECOND — b\r\n\r\n## B\r\ntext",
    "tab_indent": "\tindented",
    "nbsp": "## Heading \n- item one\n \n## Next",
    "h2_in_comment": "## Real\n<!--\n## Not a heading\n-->\n## Also real",
    "h2_in_fence": "## Real\n```\n## fenced\n---\n```\n## After",
    "duplicate_headings": "## Log\nx\n## Log\ny\n## Log\nz",
    "duplicate_dates": "## Log\n## 2026-09-01 #a\n- x\n## 2026-09-01 #a\n- y\n## 2026-09-01\n- z",
    "body_starts_with_hr": "---\nagent: X\n---\n# Title\n\n## Sec\nbody",
    "yaml_no_close": "---\nnot yaml\n\n## Sec\nbody",
    "single_reminder_line": "Latest Feedback Reminder: keep it short",
    "unicode_dash_labels": "## S\n1. RE–ENTRY — a\n2. GAP‐CHASE – b\n3. PLAIN - c\n4. COLON: d",
    "twelve_items": "## S\n" + "\n".join(f"{i}. ITEM {i} — text {i}" for i in range(1, 13)),
    "hr_in_directives": "## A\nx\n---\ntrailing note\n\n## B\ny",
    "trailing_spaces_heading": "## Heading with spaces   \nbody",
    "tag_bullets": "## Lessons\n- **#one — a**\n- plain\n- **#two — b**\n\nafter\n",
    "numbered_single": "## S\n1. only one item\nmore",
    "list_then_para_then_list": "## S\n1. A\n2. B\n\npara\n\n1. C\n2. D",
    "trailing_newlines": "## A\nbody\n\n\n",
    "leading_newlines": "\n\n## A\nbody",
    "only_heading": "## A",
    "title_blocks": "TITLE ONE\n- a\n\nTITLE TWO (note):\n- b\n\nSentence paragraph here.\n\nMIXED case Title\n",
    "comment_then_heading": "<!-- c -->\n## A\nx",
    "hr_then_hr": "a\n---\n---\nb",
    "many_hrs": "## A\n---\n\n---\nb\n---",
}


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
@pytest.mark.parametrize("field", COMPILED_FIELDS)
def test_synthetic_roundtrip(tmp_path, name, field):
    text = SYNTHETIC[name]
    fields = {f: None for f in FIELDS}
    fields[field] = text
    res = roundtrip(tmp_path / field, "DeciderAgent", fields)
    assert_partition(field, text)
    ids = [n.id for n in res["build"].nodes]
    assert len(ids) == len(set(ids))


def test_synthetic_templates_never_cut(tmp_path):
    text = "## H2\n1. one\n2. two\n---\n- **#tag** x\n"
    fields = {f: None for f in FIELDS}
    fields["system_prompt"] = text
    fields["user_prompt_template"] = text
    res = roundtrip(tmp_path, "DeciderAgent", fields)
    build = res["build"]
    assert [n.id for n in build.nodes if n.field == "system_prompt"] == ["DA.template.system"]
    assert [n.id for n in build.nodes if n.field == "user_prompt_template"] == ["DA.template.user"]
    assert D.slice_field("system_prompt", text) == [Slice(0, len(text), 1, "template", "")]


def test_large_field_linear(tmp_path):
    rng = random.Random(7)
    parts = []
    while sum(len(p) for p in parts) < 200_000:
        k = rng.randrange(5)
        if k == 0:
            parts.append(f"## Section {rng.randrange(1000)}\n")
        elif k == 1:
            parts.append(f"{rng.randrange(1, 20)}. RULE {rng.randrange(100)} — {'x' * rng.randrange(1, 80)}\n")
        elif k == 2:
            parts.append(f"- **#tag{rng.randrange(50)} — lesson** {'y' * rng.randrange(1, 60)}\n")
        elif k == 3:
            parts.append("\n")
        else:
            parts.append("prose " * rng.randrange(1, 20) + "\n")
    text = "".join(parts).rstrip("\n")
    assert len(text) >= 200_000
    fields = {f: None for f in FIELDS}
    fields["memory"] = text
    roundtrip(tmp_path, "DeciderAgent", fields)


# ----------------------------------------------------------------------------- random compositions
PIECES = [
    "## GROUND TRUTH — NON-NEGOTIABLE\n", "## Current Strategy\n", "## Log\n", "## Lessons Learned\n",
    "## 2026-09-01 #kill-geometry #risk\n", "## 2026-09-01\n", "## Latest Feedback Reminder (x)\n",
    "Latest Feedback Reminder: one line\n", "---\n", "---\r\n", "\n", "\r\n", "\t\n", " \n",
    "1. REGIME GATE — first\n", "2. EXTENSION CAP — second\n", "3. plain item\n", "10. TENTH: x\n",
    "   - indented continuation\n", "lazy continuation line\n",
    "- **#gap-chase — Never buy a vertical pop.** text\n", "- **Consider** untagged\n", "- plain bullet\n",
    "<!--\n", "-->\n", "<!-- inline --> text\n", "```\n", "```python\n",
    "# H1 title\n", "> blockquote `#nottag`\n", "TITLE BLOCK\n", "🚨 EMOJI TITLE: sub\n", "Sentence ends here.\n",
    "[[IONQ]] and [[reentry-quarantine]] #IRDM\n", "---\nagent: X\n---\n", "prose with no newline",
    "## Heading with trailing spaces   \n", "  \n", "\n\n\n",
]


@pytest.mark.parametrize("seed", range(500))
def test_random_composition_roundtrip(seed):
    rng = random.Random(seed)
    text = "".join(rng.choice(PIECES) for _ in range(rng.randrange(0, 25)))
    if rng.random() < 0.5:
        text = text.rstrip("\n")
    field = rng.choice(COMPILED_FIELDS)
    slices = assert_partition(field, text)
    assert slices[0].level == 1 and slices[0].kind == "preamble"
    nodes = D._field_nodes("DeciderAgent", field, text, owner="db", status="active", compiled="stored",
                           provenance="test")
    assert "".join(n.text for n in nodes) == text
    ids = [n.id for n in nodes]
    assert len(ids) == len(set(ids))
    for n in nodes:
        assert n.body == n.body.strip() or n.body == ""
        assert n.sep_before.strip() == "" and n.sep_after.strip() == ""
        # whitespace never ends up as its own node
        assert n.body != "" or n.node_type == "field"
    # node files round-trip through the writer/reader with the sha intact
    stamp = version_stamp("DeciderAgent", CFG, 1)
    for n in nodes[:3]:
        fm = D.node_to_frontmatter(n, stamp)
        data = b"---\n" + __import__("policy_graph.frontmatter", fromlist=["render_frontmatter"]).render_frontmatter(fm).encode() + b"\n---\n" + n.body.encode()
        from policy_graph.frontmatter import read_node_bytes
        fm2, body2 = read_node_bytes(data)
        back = D.node_from_frontmatter(fm2, body2)
        assert back.text == n.text and back.id == n.id and back.parent == n.parent


# ----------------------------------------------------------------------------- integrity
def test_corrupted_body_is_detected(tmp_path):
    fields = {f: None for f in FIELDS}
    fields["strategy_directives"] = fixture_text("decider_v21_sd.md")
    build = build_for("DeciderAgent", 21, fields)
    vdir = write_version_dir(tmp_path, "DeciderAgent", 21, build)
    target = vdir / "DA.directives.strategy.priced_kill.md"
    data = target.read_bytes()
    head, _, body = data.partition(b"\n---\n3. PRICED KILL")
    assert body, "body not found"
    target.write_bytes(head + b"\n---\n3. PRICED KILLS" + body)
    with pytest.raises(D.NodeIntegrityError):
        C.read_version_dir(vdir)


def test_monkeypatched_reader_corruption_fails_roundtrip(tmp_path, monkeypatch):
    fields = {f: None for f in FIELDS}
    fields["soul"] = fixture_text("decider_v21_soul.md")
    build = build_for("DeciderAgent", 21, fields)
    vdir = write_version_dir(tmp_path, "DeciderAgent", 21, build)
    real = C.read_node

    def corrupt(path):
        fm, body = real(path)
        return fm, body + "x"

    monkeypatch.setattr(C, "read_node", corrupt)
    with pytest.raises(D.NodeIntegrityError):
        C.read_version_dir(vdir)


def test_stored_null_compiles_to_none(tmp_path):
    fields = {f: None for f in FIELDS}
    fields["strategy_directives"] = "## A\nx"
    res = roundtrip(tmp_path, "SummarizerAgent", fields)
    assert res["stored"]["soul"] is None
    assert res["stored"]["memory"] is None
    assert res["stored"]["system_prompt"] is None
    assert res["build"].fields_meta["soul"]["stored_null"] is True
    assert C.compile_effective(res["version"])["soul"] == ""
    assert not [n for n in res["build"].nodes if n.field == "soul"]


def test_empty_field_is_group_node_with_empty_body(tmp_path):
    fields = {f: None for f in FIELDS}
    fields["soul"] = ""
    fields["memory"] = "\n"
    res = roundtrip(tmp_path, "DeciderAgent", fields)
    build = res["build"]
    soul = [n for n in build.nodes if n.field == "soul"]
    assert [n.id for n in soul] == ["DA.soul"]
    assert soul[0].body == "" and soul[0].sep_before == "" and soul[0].sep_after == ""
    mem = [n for n in build.nodes if n.field == "memory"]
    assert [n.id for n in mem] == ["DA.memory"]
    assert mem[0].body == "" and mem[0].text == "\n"
    assert build.fields_meta["soul"]["stored_empty"] is True
    assert res["stored"]["soul"] == "" and res["stored"]["memory"] == "\n"


def test_inherited_default_substitution(tmp_path):
    default = fixture_text("decider_v20_soul.md")
    inh = InheritedText(text=default, source_path="agents/decider/SOUL.default.md", git_sha="54a50e5e",
                        resolution="git-blob-at-created_at")
    fields = {f: None for f in FIELDS}
    fields["soul"] = ""
    fields["strategy_directives"] = fixture_text("decider_v19_sd.md")
    res = roundtrip(tmp_path, "DeciderAgent", fields, version=19, inherited={"soul": inh, "memory": None})
    build, ver = res["build"], res["version"]
    inherited_nodes = [n for n in build.nodes if n.owner == "default-file"]
    assert inherited_nodes and all(n.status == "inherited" and n.compiled == "effective-only" for n in inherited_nodes)
    assert {n.field for n in inherited_nodes} == {"soul"}
    assert "DA.soul.mission" in {n.id for n in inherited_nodes}
    assert all(n.extra["inherited_from"] == "agents/decider/SOUL.default.md" for n in inherited_nodes)
    assert build.compile_order["soul"] == []
    assert build.fields_meta["soul"]["inherited"] is True
    assert build.fields_meta["soul"]["inherited_git_sha"] == "54a50e5e"
    assert C.compile_stored(ver)["soul"] == ""
    assert C.compile_effective(ver)["soul"] == default
    # inherited nodes are never in the stored compile and never owner db
    assert all(ver.nodes[i].owner == "db" for f in FIELDS for i in ver.manifest["compile_order"][f])


def test_inherited_ignored_when_field_is_stored(tmp_path):
    inh = InheritedText(text="## Mission\nignored", source_path="x", git_sha=None, resolution="worktree")
    fields = {f: None for f in FIELDS}
    fields["soul"] = "## Mission\nstored text"
    res = roundtrip(tmp_path, "DeciderAgent", fields, inherited={"soul": inh})
    assert not [n for n in res["build"].nodes if n.owner == "default-file"]
    assert res["build"].fields_meta["soul"]["inherited"] is False
    assert C.compile_effective(res["version"])["soul"] == "## Mission\nstored text"


def test_runtime_preview_assembly_order(tmp_path):
    fields = {
        "system_prompt": fixture_text("decider_v21_system.md"),
        "user_prompt_template": fixture_text("decider_v21_user.md"),
        "strategy_directives": fixture_text("decider_v21_sd.md"),
        "soul": fixture_text("decider_v21_soul.md"),
        "memory": fixture_text("decider_v21_memory.md"),
    }
    res = roundtrip(tmp_path, "DeciderAgent", fields, version=21)
    prev = C.compile_runtime_preview(res["version"], is_margin_account=False)
    system, user = prev["system"], prev["user"]
    assert "{strategy_directives}" not in system
    i_soul = system.index("## AGENT IDENTITY")
    i_strat = system.index("## GROUND TRUTH — NON-NEGOTIABLE")
    i_mem = system.index("## LESSONS FROM EXPERIENCE")
    assert i_strat < i_soul < i_mem, "directives substituted into the template, then soul, then memory"
    assert system.startswith(fields["system_prompt"].split("{strategy_directives}")[0])
    assert prev["fires"]["DA.code.crowd_fade"] is True
    assert prev["fires"]["DA.code.cash_playbook"] is True
    assert prev["fires"]["DA.code.json_fallback"] is False
    assert user.startswith(fields["user_prompt_template"].rstrip())
    assert "CROWD-FADE" in user and "⏳ CASH ACCOUNT PLAYBOOK" in user
    assert "per-cycle data omitted" in prev["label"]
    margin = C.compile_runtime_preview(res["version"], is_margin_account=True)
    assert margin["fires"]["DA.code.cash_playbook"] is False


def test_bundle_root_first_then_lexicographic(tmp_path):
    fields = {f: None for f in FIELDS}
    fields["strategy_directives"] = fixture_text("decider_v21_sd.md")
    res = roundtrip(tmp_path, "DeciderAgent", fields, version=21)
    text = C.bundle(res["version"])
    markers = [line for line in text.split("\n") if line.startswith("<!-- ") and line.endswith(".md -->")]
    assert markers[0] == "<!-- DA.root.md -->"
    rest = [m[5:-7] for m in markers[1:]]
    assert rest == sorted(rest)
    assert text.endswith("\n") and not text.startswith("\n")


def test_rebuild_compile_order_inserts_new_node_after_siblings(tmp_path):
    fields = {f: None for f in FIELDS}
    fields["strategy_directives"] = fixture_text("decider_v21_sd.md")
    res = roundtrip(tmp_path, "DeciderAgent", fields, version=21)
    ver = res["version"]
    old = list(ver.manifest["compile_order"]["strategy_directives"])
    new = D.Node(id="DA.directives.strategy.n9", agent="DeciderAgent", title="n9", node_type="rule",
                 parent="DA.directives.strategy", field="strategy_directives", body="9. NEW — rule")
    ver.nodes[new.id] = new
    del ver.nodes["DA.directives.strategy.harvest"]
    order = C.rebuild_compile_order(ver, {new.id, "DA.directives.strategy.harvest"})["strategy_directives"]
    assert order[-1] == new.id
    assert "DA.directives.strategy.harvest" not in order
    assert [i for i in order if i in old] == [i for i in old if i != "DA.directives.strategy.harvest"]
    assert ver.nodes[new.id].sep_after == ""  # last node of the field is normalised
    assert ver.nodes["DA.directives.strategy.n8"].sep_after == "\n\n"  # no longer last: separator restored
