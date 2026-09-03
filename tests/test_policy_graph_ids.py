"""Policy graph ids and taxonomy (spec §2.2 / §14 item 2). DB-free."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from policy_graph import decompose as D
from policy_graph.model import (
    COLORS, FIELDS, HEADING_ALIASES, ID_RE, NODE_TYPES, OWNERS, POLARITIES, RowMeta, STATUSES, COMPILED,
    normalize_heading, slug_for_heading, slugify,
)

FX = Path(__file__).parent / "fixtures" / "policy_graph"
INDEX = json.loads((FX / "INDEX.json").read_text(encoding="utf-8"))
CFG = "cfg_test"


def fixture_text(name: str) -> str:
    return (FX / name).read_bytes().decode("utf-8")


def field_ids(agent: str, field: str, text: str) -> list:
    return [n.id for n in D._field_nodes(agent, field, text, owner="db", status="active", compiled="stored",
                                         provenance="t")]


def field_nodes(agent: str, field: str, text: str) -> dict:
    return {n.id: n for n in D._field_nodes(agent, field, text, owner="db", status="active", compiled="stored",
                                            provenance="t")}


def build(agent: str, fields: dict, version: int = 1, **kw):
    full = {f: None for f in FIELDS}
    full.update(fields)
    meta = RowMeta(prompt_version_id=599, created_at=datetime(2026, 9, 2), created_by="claude_code",
                   description="v21", is_active=True)
    return D.decompose_row(agent, CFG, version, full, meta=meta, inherited=kw.get("inherited", {}),
                           code_nodes=kw.get("code_nodes", []), ltm_nodes=kw.get("ltm_nodes", []),
                           is_margin_account=False)


# ----------------------------------------------------------------------------- alias table / slugs
ALIAS_CASES = [
    ("GROUND TRUTH — NON-NEGOTIABLE", "ground_truth"),
    ("Current Strategy (2026-09-02 — regime-gated controlled pullbacks with priced kills)", "strategy"),
    ("Current Strategy", "strategy"),
    ("Latest Feedback Reminder (2026-09-02)", "reminder"),
    ("Mission (shared across all agents — preserve verbatim)", "mission"),
    ("Shared Principles (preserve verbatim)", "principles"),
    ("Core Philosophy", "core_philosophy"),
    ("Decision Style", "decision_style"),
    ("Risk Management", "risk_management"),
    ("Lessons Learned", "lessons"),
    ("Patterns to Watch", "patterns"),
    ("Mistakes to Avoid", "mistakes"),
    ("Log", "log"),
    ("Evidence Discipline", "evidence_discipline"),
    ("Per-Agent Edge", "per_agent_edge"),
    ("Current Evolution Focus", "evolution_focus"),
    ("Operating Identity", "operating_identity"),
    ("Review Style", "review_style"),
    ("Extraction Style", "extraction_style"),
    ("Catalyst-Provenance Standard", "catalyst_provenance"),
    ("What the Decider actually uses", "decider_uses"),
    ("Source Quality Notes", "source_quality"),
    ("Extraction Patterns", "extraction_patterns"),
    ("Media-Manipulation Watch", "media_manipulation"),
    ("ANTI-HALLUCINATION RULES:", "anti_hallucination"),
    ("PRIMARY MISSION (in order of priority)", "primary_mission"),
    ("ACCOUNT MODE", "account_mode"),
    ("HOLDING WINDOW & DATA GUARDRAILS", "holding_window"),
    ("DAILY PACING & LIMITS", "daily_pacing"),
    ("💰 HARD SELL RULE (NO CROWD-FADE OVERRIDES)", "hard_sell_rule"),
    ("🚫 CROWD-FADE REASONING", "crowd_fade"),
    ("⏳ CASH ACCOUNT PLAYBOOK (1–5 TRADING DAYS)", "cash_playbook"),
    ("🚨 LOSER MANAGEMENT — NO DEFAULT “HOLD ALL”", "loser_management"),
    ("HOLD DURATION AWARENESS", "hold_duration"),
    ("REASON CONTENT (≤140 chars)", "reason_content"),
    ("CORE DECIDER RULES", "core_rules"),
    ("HOLDING TRIAGE", "holding_triage"),
    ("PROFIT HARVESTING", "profit_harvesting"),
    ("LOSS CONTAINMENT", "loss_containment"),
    ("BUY SELECTION", "buy_selection"),
    ("CASH DISCIPLINE", "cash_discipline"),
    ("Feedback Calibration", "feedback_calibration"),
    ("Anti-patterns in my own feedback", "anti_patterns"),
    ("Cross-Agent Observations", "cross_agent"),
    ("Current Battle Focus", "battle_focus"),
    ("Failure Pattern to Hunt", "failure_pattern"),
    ("STYLE", "style"),
    ("GROUND TRUTH — PORTFOLIO STATE (NON-NEGOTIABLE)", "ground_truth"),
    ("🚨 GROUND TRUTH: YOUR DECISIONS MUST MATCH YOUR ACTUAL PORTFOLIO", "ground_truth"),
]


@pytest.mark.parametrize("heading,slug", ALIAS_CASES, ids=[s for _, s in ALIAS_CASES])
def test_alias_table(heading, slug):
    assert slug_for_heading(heading) == slug


def test_every_alias_entry_resolves_to_itself():
    for prefix, slug in HEADING_ALIASES:
        assert slug_for_heading(prefix.upper()) == slug
        assert slug_for_heading("## " + prefix.title() + " (x)") in (slug, slug_for_heading(prefix))


def test_generic_slug_rules():
    assert slug_for_heading("Setup-Specific Kill Discipline") == "setup_specific_kill_discipline"
    assert slug_for_heading("Current evidence-backed test: technical pullback quality") == "current_evidence_backed_test"
    assert slug_for_heading("Entry and Rotation") == "entry_rotation"
    assert slug_for_heading("The A of the B for the C in D with E") == "b_c_d_e"
    assert slug_for_heading("AUDIT ORDER (2026-09-02):") == "audit_order"
    assert len(slug_for_heading("x" * 100)) <= 40
    assert slug_for_heading("") == "section"
    assert slugify("RE-ENTRY QUARANTINE") == "re_entry_quarantine"
    assert slugify("reentry-quarantine") == "reentry_quarantine"
    assert slugify("GAP‐CHASE") == "gap_chase"
    assert normalize_heading("🚨 GROUND TRUTH: X") == "ground truth"


# ----------------------------------------------------------------------------- v21 ids (spec §2.2)
def test_v21_directive_ids():
    ids = field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v21_sd.md"))
    assert ids == [
        "DA.directives", "DA.directives.ground_truth", "DA.directives.strategy",
        "DA.directives.strategy.regime_gate", "DA.directives.strategy.extension_cap",
        "DA.directives.strategy.priced_kill", "DA.directives.strategy.re_entry_quarantine",
        "DA.directives.strategy.correlation", "DA.directives.strategy.harvest",
        "DA.directives.strategy.n7", "DA.directives.strategy.n8",
    ]
    nodes = field_nodes("DeciderAgent", "strategy_directives", fixture_text("decider_v21_sd.md"))
    pk = nodes["DA.directives.strategy.priced_kill"]
    assert pk.node_type == "rule" and pk.title == "PRICED KILL" and pk.parent == "DA.directives.strategy"
    assert pk.polarity == "gate" and pk.polarity_source == "override"
    assert pk.body.startswith("3. PRICED KILL — ") and pk.sep_after == "\n" and pk.sep_before == ""
    assert pk.order == 5
    assert nodes["DA.directives.ground_truth"].locked is True
    assert nodes["DA.directives.strategy"].polarity == "mixed"
    assert nodes["DA.directives.strategy.harvest"].polarity == "action"
    assert nodes["DA.directives"].node_type == "field" and nodes["DA.directives"].body == ""


def test_v20_strategy_shares_id_with_v21_and_keeps_plain_bullets():
    ids = field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v20_sd.md"))
    assert ids == ["DA.directives", "DA.directives.ground_truth", "DA.directives.strategy"]


def test_v21_soul_ids():
    ids = field_ids("DeciderAgent", "soul", fixture_text("decider_v21_soul.md"))
    assert ids == ["DA.soul", "DA.soul.mission", "DA.soul.principles", "DA.soul.identity",
                   "DA.soul.core_philosophy", "DA.soul.decision_style", "DA.soul.risk_management"]
    nodes = field_nodes("DeciderAgent", "soul", fixture_text("decider_v21_soul.md"))
    assert nodes["DA.soul"].body == "# Decider Agent — Soul"
    assert nodes["DA.soul.principles"].body.endswith("or prior lesson.\n\n---")
    assert nodes["DA.soul.identity"].body.startswith("You are a disciplined, aggressive short-swing trader")
    assert nodes["DA.soul.identity"].node_type == "identity"
    assert nodes["DA.soul.mission"].locked and nodes["DA.soul.principles"].locked
    assert not nodes["DA.soul.core_philosophy"].locked
    assert nodes["DA.soul.core_philosophy"].polarity == "principle"
    assert nodes["DA.soul.risk_management"].polarity == "gate"
    assert set(nodes["DA.soul.core_philosophy"].tickers) >= {"IONQ", "RKLB", "MRVL", "ORCL"}


def test_v21_memory_ids():
    ids = field_ids("DeciderAgent", "memory", fixture_text("decider_v21_memory.md"))
    assert ids == [
        "DA.memory", "DA.memory.lessons", "DA.memory.lessons.gap_chase", "DA.memory.lessons.extension_chase",
        "DA.memory.lessons.regime", "DA.memory.lessons.priced_kill", "DA.memory.lessons.reentry_quarantine",
        "DA.memory.lessons.n6", "DA.memory.patterns", "DA.memory.mistakes", "DA.memory.mistakes.unexecutable_gate",
        "DA.memory.log", "DA.memory.log.2026_06_29_irdm", "DA.memory.log.2026_09_02_regime",
        "DA.memory.log.2026_09_01_kill_geometry", "DA.memory.log.2026_09_01_technical_pullback",
    ]
    nodes = field_nodes("DeciderAgent", "memory", fixture_text("decider_v21_memory.md"))
    assert nodes["DA.memory"].body.startswith("---\nagent: DeciderAgent")
    assert "# Decider Agent — Memory" in nodes["DA.memory"].body and "Conventions" in nodes["DA.memory"].body
    assert nodes["DA.memory"].tags == []  # `#tags` sits inside backticks
    assert nodes["DA.memory.log"].body.startswith("## Log") and "Template for new entries" in nodes["DA.memory.log"].body
    assert nodes["DA.memory.log"].node_type == "section" and nodes["DA.memory.log"].polarity == "structure"
    for entry in ("DA.memory.log.2026_06_29_irdm", "DA.memory.log.2026_09_02_regime"):
        assert nodes[entry].parent == "DA.memory.log" and nodes[entry].node_type == "entry"
    assert nodes["DA.memory.log.2026_06_29_irdm"].title == "2026-06-29 #IRDM #gap-chase #exit-liquidity"
    assert nodes["DA.memory.log.2026_06_29_irdm"].tags == ["irdm", "gap-chase", "exit-liquidity"]
    assert nodes["DA.memory.log.2026_06_29_irdm"].tickers == ["IRDM"]
    assert "front-run-not-chase" in nodes["DA.memory.log.2026_06_29_irdm"].links
    assert nodes["DA.memory.lessons.gap_chase"].node_type == "lesson"
    assert nodes["DA.memory.lessons.gap_chase"].title == "#gap-chase — Never buy a vertical pop."
    assert nodes["DA.memory.lessons.n6"].title.startswith("Consider 2–3 of the best setups")
    assert "Controlled pullback" in nodes["DA.memory.patterns"].body
    assert nodes["DA.memory.lessons"].polarity == "evidence"


def test_v20_memory_has_untagged_dated_entry():
    ids = field_ids("DeciderAgent", "memory", fixture_text("decider_v20_memory.md"))
    assert "DA.memory.log.2026_08_27" in ids
    assert "DA.memory.lessons.gap_chase" in ids and "DA.memory.lessons.n2" in ids


def test_log_comment_line_never_becomes_a_node():
    for e in INDEX:
        if e["field"] != "memory":
            continue
        nodes = field_nodes(e["agent_type"], "memory", fixture_text(e["file"]))
        for i in nodes:
            assert "yyyy" not in i.lower() and "ticker_xyz" not in i.lower(), (e["file"], i)
            assert "tag1" not in i, (e["file"], i)
        assert not any(n.body.startswith("## YYYY") for n in nodes.values())


# ----------------------------------------------------------------------------- other agents / versions
def test_summarizer_v16_directive_ids():
    ids = field_ids("SummarizerAgent", "strategy_directives", fixture_text("summarizer_v16_sd.md"))
    assert ids == ["SA.directives", "SA.directives.ground_truth", "SA.directives.catalyst_provenance"]


def test_summarizer_v17_memory_ids():
    ids = field_ids("SummarizerAgent", "memory", fixture_text("summarizer_v17_memory.md"))
    assert ids[:5] == ["SA.memory", "SA.memory.source_quality", "SA.memory.extraction_patterns",
                       "SA.memory.media_manipulation", "SA.memory.log"]
    assert ids[5:] == ["SA.memory.log.2026_09_02_pipeline", "SA.memory.log.2026_09_02_edge",
                       "SA.memory.log.2026_09_01_catalyst_provenance"]


def test_feedback_v8_memory_ids():
    ids = field_ids("FeedbackAgent", "memory", fixture_text("feedback_v08_memory.md"))
    assert ids == [
        "FA.memory", "FA.memory.log.2026_06_20", "FA.memory.log.2026_06_24", "FA.memory.log.2026_06_25",
        "FA.memory.log.2026_06_25_2", "FA.memory.log.2026_08_04", "FA.memory.log.2026_08_21",
        "FA.memory.log.2026_09_01", "FA.memory.log.2026_09_02_meta", "FA.memory.log.2026_09_02_meta_2",
        "FA.memory.log.2026_09_02_meta_3", "FA.memory.log.2026_09_02_meta_4",
    ]
    nodes = field_nodes("FeedbackAgent", "memory", fixture_text("feedback_v08_memory.md"))
    assert all(n.parent == "FA.memory" for i, n in nodes.items() if i != "FA.memory")
    assert nodes["FA.memory"].body == ""
    assert all(n.status == "inert" for n in nodes.values())


def test_feedback_v8_directives_title_blocks():
    ids = field_ids("FeedbackAgent", "strategy_directives", fixture_text("feedback_v08_sd.md"))
    assert ids[:4] == ["FA.directives", "FA.directives.ground_truth", "FA.directives.anti_hallucination",
                       "FA.directives.audit_order"]
    nodes = field_nodes("FeedbackAgent", "strategy_directives", fixture_text("feedback_v08_sd.md"))
    assert nodes["FA.directives"].body.startswith("Keep total output length")
    assert nodes["FA.directives"].body.endswith("recordkeeping gaps.")
    assert nodes["FA.directives.ground_truth"].body.startswith("GROUND TRUTH — PORTFOLIO STATE ENFORCEMENT:")
    assert "FA.directives.audit_order.regime" in ids and "FA.directives.audit_order.re_entry" in ids


def test_feedback_v7_soul_identity_after_hr():
    nodes = field_nodes("FeedbackAgent", "soul", fixture_text("feedback_v07_soul.md"))
    ids = list(nodes)
    assert ids[:4] == ["FA.soul", "FA.soul.mission", "FA.soul.principles", "FA.soul.identity"]
    assert nodes["FA.soul"].body == "" and nodes["FA.soul"].text == ""
    assert nodes["FA.soul.identity"].body.startswith("# Feedback Agent — Soul")
    assert "FA.soul.operating_identity" in ids and "FA.soul.battle_focus" in ids and "FA.soul.failure_pattern" in ids
    assert all(n.status == "active" for n in nodes.values())


def test_decider_v0_title_blocks():
    ids = field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v00_sd.md"))
    sections = [i for i in ids if i.count(".") == 2]
    assert sections == [f"DA.directives.{s}" for s in (
        "ground_truth", "primary_mission", "account_mode", "holding_window", "daily_pacing", "hard_sell_rule",
        "crowd_fade", "cash_playbook", "loser_management", "hold_duration", "reason_content")]
    nodes = field_nodes("DeciderAgent", "strategy_directives", fixture_text("decider_v00_sd.md"))
    assert nodes["DA.directives"].body == ""
    # sentence paragraphs stay inside the preceding slice
    assert "When these conflict" in nodes["DA.directives.primary_mission.n3"].body
    assert "If there is any ambiguity" in nodes["DA.directives.reason_content"].body


def test_decider_v7_reminder_plus_eight_blocks():
    ids = field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v07_sd.md"))
    level2 = [i for i in ids if i.count(".") == 2]
    assert level2 == [f"DA.directives.{s}" for s in (
        "reminder", "ground_truth", "core_rules", "holding_triage", "profit_harvesting", "loss_containment",
        "buy_selection", "cash_discipline", "style")]
    nodes = field_nodes("DeciderAgent", "strategy_directives", fixture_text("decider_v07_sd.md"))
    assert nodes["DA.directives.reminder"].node_type == "reminder"
    assert nodes["DA.directives.reminder"].polarity == "caution"
    assert [i for i in ids if i.startswith("DA.directives.core_rules.")] == [f"DA.directives.core_rules.n{k}" for k in range(1, 12)]
    assert "   - Fresh catalyst" in nodes["DA.directives.core_rules.n7"].body


def test_decider_v19_single_reminder_line():
    ids = field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v19_sd.md"))
    assert ids == ["DA.directives", "DA.directives.reminder"]
    nodes = field_nodes("DeciderAgent", "strategy_directives", fixture_text("decider_v19_sd.md"))
    assert nodes["DA.directives"].text == ""


def test_reminder_section_form_shares_id_with_bare_line():
    text = "## GROUND TRUTH\n- x\n\n## Latest Feedback Reminder (2026-09-09)\nkeep it short"
    ids = field_ids("DeciderAgent", "strategy_directives", text)
    assert ids == ["DA.directives", "DA.directives.ground_truth", "DA.directives.reminder"]


def test_v18_and_v14_generic_section_slugs():
    assert field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v18_sd.md")) == [
        "DA.directives", "DA.directives.ground_truth", "DA.directives.current_evidence_backed_test",
        *[f"DA.directives.current_evidence_backed_test.n{k}" for k in range(1, 6)],
        "DA.directives.existing_execution_discipline"]
    assert field_ids("DeciderAgent", "strategy_directives", fixture_text("decider_v14_sd.md")) == [
        "DA.directives", "DA.directives.ground_truth", "DA.directives.evidence_calibrated_execution",
        "DA.directives.setup_specific_kill_discipline", "DA.directives.entry_rotation"]


def test_decider_v3_memory_entry_without_log_section():
    assert field_ids("DeciderAgent", "memory", fixture_text("decider_v03_memory.md")) == [
        "DA.memory", "DA.memory.log.2026_05_14"]


# ----------------------------------------------------------------------------- collisions / dated / child rules
def test_collision_suffixes_in_document_order():
    text = "## Log\na\n## Log\nb\n## Log\nc"
    assert field_ids("DeciderAgent", "memory", text) == ["DA.memory", "DA.memory.log", "DA.memory.log_2", "DA.memory.log_3"]


def test_dated_entries_and_tag_case():
    text = "## 2026-09-01 #IRDM #x\n- a\n## 2026-09-01 #IRDM\n- b\n## 2026-09-01\n- c\n## 2026-09-01\n- d"
    assert field_ids("DeciderAgent", "memory", text) == [
        "DA.memory", "DA.memory.log.2026_09_01_irdm", "DA.memory.log.2026_09_01_irdm_2",
        "DA.memory.log.2026_09_01", "DA.memory.log.2026_09_01_2"]


def test_dated_heading_outside_comment_only_when_digits():
    text = "## Log\n## YYYY-MM-DD #tag1 #tag2\n- x"
    ids = field_ids("DeciderAgent", "memory", text)
    # generic slug = first 4 significant words (model.slug_for_heading), not the spec's 5-word example
    assert ids == ["DA.memory", "DA.memory.log", "DA.memory.yyyy_mm_dd_tag1"]


def test_child_rule_slugs_and_ordinals():
    text = ("## S\n1. REGIME GATE — a\n2. RE-ENTRY QUARANTINE: b\n3. plain text - c\n4. FOO - d\n"
            "5. RE–ENTRY – unicode\n6. REGIME GATE — dup")
    ids = field_ids("DeciderAgent", "strategy_directives", text)
    assert ids[2:] == ["DA.directives.s.regime_gate", "DA.directives.s.re_entry_quarantine", "DA.directives.s.n3",
                       "DA.directives.s.foo", "DA.directives.s.re_entry", "DA.directives.s.regime_gate_2"]


def test_single_numbered_item_not_split_and_plain_bullets_not_split():
    assert field_ids("DeciderAgent", "strategy_directives", "## S\n1. only\n- a\n- b") == ["DA.directives", "DA.directives.s"]


def test_tag_bullet_run_splits_every_item():
    text = "## Lessons Learned\n*intro*\n- **#gap-chase — A.** x\n- **Consider** y\n- **#priced-kill** z\n- plain #tag"
    ids = field_ids("DeciderAgent", "memory", text)
    assert ids == ["DA.memory", "DA.memory.lessons", "DA.memory.lessons.gap_chase", "DA.memory.lessons.n2",
                   "DA.memory.lessons.priced_kill", "DA.memory.lessons.n4"]
    nodes = field_nodes("DeciderAgent", "memory", text)
    assert nodes["DA.memory.lessons"].body == "## Lessons Learned\n*intro*"
    assert nodes["DA.memory.lessons.n2"].title == "Consider"


def test_hr_in_directives_yields_note():
    text = "## Alpha\nx\n---\ntrailing note\n\n## Beta\ny"
    ids = field_ids("DeciderAgent", "strategy_directives", text)
    assert ids == ["DA.directives", "DA.directives.alpha", "DA.directives.note", "DA.directives.beta"]
    nodes = field_nodes("DeciderAgent", "strategy_directives", text)
    assert nodes["DA.directives.alpha"].body == "## Alpha\nx\n---"
    assert nodes["DA.directives.note"].node_type == "note" and nodes["DA.directives.note"].body == "trailing note"


def test_h2_inside_comment_and_fence_are_not_cut():
    text = "## Real\n<!--\n## Not\n-->\n```\n## Fenced\n---\n```\n## After"
    ids = field_ids("DeciderAgent", "memory", text)
    assert ids == ["DA.memory", "DA.memory.real", "DA.memory.after"]


def test_tags_tickers_links_extraction():
    body = "See [[IONQ]] and [[reentry-quarantine|alias]] #Gap-Chase #IRDM `#nottag` <!-- #hidden --> feedback#1237 #1"
    assert D.extract_tags(body) == ["gap-chase", "irdm"]
    assert D.extract_tickers(body) == ["IONQ", "IRDM"]
    assert D.extract_links(body) == ["IONQ", "reentry-quarantine"]


# ----------------------------------------------------------------------------- whole-row structure
def test_full_row_structure_root_parents_filenames():
    fields = {
        "system_prompt": fixture_text("decider_v21_system.md"),
        "user_prompt_template": fixture_text("decider_v21_user.md"),
        "strategy_directives": fixture_text("decider_v21_sd.md"),
        "soul": fixture_text("decider_v21_soul.md"),
        "memory": fixture_text("decider_v21_memory.md"),
    }
    code = [D.Node(id="DA.code.crowd_fade", agent="DeciderAgent", title="CROWD-FADE", node_type="code", parent="DA.code",
                   field=None, body="x", owner="code", status="read-only", compiled="never", locked=True,
                   extra={"position": "user_template_tail", "fires": True})]
    ltm = [D.Node(id="DA.ltm.20", agent="DeciderAgent", title="row 20", node_type="ltm", parent="DA.ltm", field=None,
                  body="- [lesson] (IONQ) x", owner="decider_memory", status="active", compiled="never", locked=True)]
    b = build("DeciderAgent", fields, version=21, code_nodes=code, ltm_nodes=ltm)
    nodes = {n.id: n for n in b.nodes}
    assert len(nodes) == len(b.nodes)
    roots = [n for n in b.nodes if n.node_type == "root"]
    assert len(roots) == 1 and roots[0].id == "DA.root" == b.root_id and roots[0].parent is None
    for n in b.nodes:
        assert ID_RE.match(n.id), n.id
        assert n.node_type in NODE_TYPES and n.polarity in POLARITIES and n.owner in OWNERS
        assert n.status in STATUSES and n.compiled in COMPILED
        assert f"{n.id}.md" == n.id + ".md"
        if n.id != "DA.root":
            assert n.parent in nodes, n.id
            # parents chain to the root without cycles
            seen, cur = set(), n.id
            while cur is not None:
                assert cur not in seen
                seen.add(cur)
                cur = nodes[cur].parent
            assert "DA.root" in seen
    assert nodes["DA.template.system"].locked and nodes["DA.template.system"].body == fields["system_prompt"]
    assert nodes["DA.template.user"].node_type == "template" and not nodes["DA.template.user"].locked
    assert nodes["DA.template.system"].polarity == "structure"
    assert nodes["DA.code.crowd_fade"].parent == "DA.code" and nodes["DA.code"].parent == "DA.root"
    assert nodes["DA.ltm.20"].parent == "DA.ltm" and nodes["DA.ltm"].parent == "DA.root"
    assert nodes["DA.runtime.inputs"].owner == "runtime" and nodes["DA.runtime.inputs"].node_type == "data"
    assert "{available_cash}" in nodes["DA.runtime.inputs"].body
    assert "not policy text" in nodes["DA.runtime.inputs"].body
    assert nodes["DA.root"].locked and nodes["DA.root"].compiled == "never"
    assert "policy version 21" in nodes["DA.root"].body and "prompt_versions#599" in nodes["DA.root"].body
    assert b.edges == []
    assert set(b.compile_order) == set(FIELDS)
    for f in FIELDS:
        assert all(nodes[i].owner == "db" and nodes[i].field == f for i in b.compile_order[f])
    # orders per field are 0..n-1 in document order
    for f in ("strategy_directives", "soul", "memory"):
        assert [nodes[i].order for i in b.compile_order[f]] == list(range(len(b.compile_order[f])))


def test_feedback_status_inert_except_soul():
    fields = {"system_prompt": "s", "user_prompt_template": "u", "strategy_directives": "## A\nx",
              "soul": "## Mission\nm", "memory": "## 2026-01-01\n- x"}
    b = build("FeedbackAgent", fields, version=8)
    for n in b.nodes:
        if n.field in ("system_prompt", "user_prompt_template", "strategy_directives", "memory"):
            assert n.status == "inert", n.id
        elif n.field == "soul":
            assert n.status == "active", n.id


def test_unknown_agent_rejected():
    with pytest.raises(ValueError):
        build("CompanyExtractionAgent", {"soul": "x"})


def test_colors_mirror_has_all_polarities():
    for p in POLARITIES:
        if p != "structure":
            assert p in COLORS
    assert COLORS["root"] == "#42c9ff" and COLORS["gate"] == "#ff5f73"
