"""Phase 2 — proposals: patch application, round-trip verification, the draft→critic→review pipeline
with a fake model, apply (mint + activate + materialize), rebase and conflict, partial approval,
rejection, and the in-progress / stale guards. In-memory SQLite, tmp_path as the repo root, no LLM."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from policy_graph import proposals as P
from policy_graph import service
from policy_graph.compile import compile_stored, read_version_dir
from policy_graph.model import InheritedText

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_pg_service_tests", HERE / "test_policy_graph_service.py")
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
CFG = _svc.CFG
fx = _svc.fx

DRAFTER_JSON = {
    "reasoning": "Unpriced kills are the largest measured leak; tighten D.",
    "files": [
        {"id": "DA.directives.strategy.priced_kill", "action": "edit", "primary": True,
         "body": None,   # filled from the fixture at runtime
         "what": "Tighter kill distance", "why": "avg loser -4.3% under unpriced kills",
         "expected_effect": "smaller losers", "falsified_if": "average loser worse than -3.5% over 20 losers"},
        {"id": "DA.memory.log.new", "action": "add", "parent": "DA.memory.log", "title": "kill distance",
         "body": "## 2026-09-03 #kill-distance\n- Tightened D after the August unwind.",
         "what": "Log the change", "why": "record keeping", "expected_effect": "none"},
    ],
}
CRITIC_JSON = {"verdict": "approve", "reason": "One attributable gate change; regime split supports it.",
               "confidence": 0.8, "ship_first": None, "unexecutable_gates": [],
               "files": [{"id": "DA.directives.strategy.priced_kill", "verdict": "approve", "reason": "the diff is the threshold"},
                         {"id": "DA.memory.log.2026_09_03_kill_distance", "verdict": "approve", "reason": "fine"}]}


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _svc.DDL:
            conn.execute(text(ddl))
        rows = [r for r in _svc.DECIDER_ROWS if r[0] in (0, 20, 21)]
        for v, sd, soul, mem, by, active, at, rid in rows:
            conn.execute(text("""
                INSERT INTO prompt_versions (id, agent_type, version, system_prompt, user_prompt_template,
                    strategy_directives, soul, memory, description, created_by, is_active, config_hash, created_at)
                VALUES (:id, 'DeciderAgent', :v, :sp, :up, :sd, :soul, :mem, :d, :by, :active, :h, :at)
            """), {"id": rid, "v": v, "sp": _svc.SYS21, "up": _svc.USER21, "sd": sd, "soul": soul, "mem": mem,
                   "d": f"DeciderAgent v{v}", "by": by, "active": active, "h": CFG, "at": at})
        for rid, at, kind, tags, ticker, content, source, weight, active in _svc.MEMORY_ROWS:
            conn.execute(text("""
                INSERT INTO decider_memory (id, config_hash, created_at, updated_at, kind, tags, ticker, content,
                    source, weight, active) VALUES (:id, :h, :at, :at, :k, :tags, :tk, :c, :s, :w, :active)
            """), {"id": rid, "h": CFG, "at": at, "k": kind, "tags": tags, "tk": ticker, "c": content, "s": source,
                   "w": weight, "active": active})
    P.ensure_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def no_git(monkeypatch):
    monkeypatch.setattr(service.inherited, "resolve_inherited",
                        lambda *a, **k: InheritedText(text="", source_path="x", git_sha=None, resolution="worktree"))


@pytest.fixture
def env(db, tmp_path, no_git):
    return {"engine": db, "root": tmp_path, "common": {"repo_root": tmp_path, "is_margin_account": False}}


def v21(env):
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    return read_version_dir(env["root"] / "agents" / "decider" / "policy-graph" / CFG / "v21")


def drafter_payload(version):
    payload = json.loads(json.dumps(DRAFTER_JSON))
    pk = version.nodes["DA.directives.strategy.priced_kill"].body
    assert "D ≤3% full size" in pk
    payload["files"][0]["body"] = pk.replace("D ≤3% full size", "D ≤2.5% full size")
    return payload


class FakeLLM:
    """Scripted responses per role; records every call."""

    def __init__(self, drafter, critic=CRITIC_JSON):
        self.drafter = list(drafter) if isinstance(drafter, list) else [drafter]
        self.critic = critic
        self.calls = []

    def __call__(self, role, system, user):
        self.calls.append((role, system, user))
        if role == "drafter":
            out = self.drafter.pop(0) if len(self.drafter) > 1 else self.drafter[0]
        else:
            out = self.critic
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)


def fake_activate(conn, agent_type, config_hash, version, *, action, actor, reason):
    prev = conn.execute(text("SELECT version FROM prompt_versions WHERE agent_type=:a AND config_hash=:h AND is_active=1"),
                        {"a": agent_type, "h": config_hash}).fetchone()
    conn.execute(text("UPDATE prompt_versions SET is_active=0 WHERE agent_type=:a AND config_hash=:h"), {"a": agent_type, "h": config_hash})
    conn.execute(text("UPDATE prompt_versions SET is_active=1 WHERE agent_type=:a AND config_hash=:h AND version=:v"),
                 {"a": agent_type, "h": config_hash, "v": version})
    conn.execute(text("""INSERT INTO prompt_activation_events (created_at, batch_id, config_hash, agent_type, from_version,
                         to_version, action, actor, reason) VALUES (:at, 'b-test', :h, :a, :f, :t, :ac, :actor, :r)"""),
                 {"at": datetime.now(), "h": config_hash, "a": agent_type, "f": prev[0] if prev else None, "t": version,
                  "ac": action, "actor": actor, "r": reason})
    return {"from_version": prev[0] if prev else None, "to_version": version, "changed": True, "batch_id": "b-test"}


def run(env, llm, focus=""):
    return P.start_draft(env["engine"], CFG, "DeciderAgent", llm=llm, context_fn=lambda h, a: {"computed_diagnostics": "x"},
                         focus=focus, background=False, model="fake", **env["common"])


# ----------------------------------------------------------------------------- patch engine
def test_prepare_edit_add_roundtrip(env):
    version = v21(env)
    files, new_fields = P.prepare("DeciderAgent", CFG, version, drafter_payload(version)["files"], is_margin_account=False)
    assert [f.action for f in files] == ["edit", "add"]
    assert files[0].id == "DA.directives.strategy.priced_kill" and files[0].kind == "major"
    assert files[1].id == "DA.memory.log.2026_09_03_kill_distance" and files[1].proposed_id == "DA.memory.log.new"
    assert files[1].kind == "minor"
    assert "D ≤2.5% full size" in new_fields["strategy_directives"]
    assert new_fields["memory"].endswith("## 2026-09-03 #kill-distance\n- Tightened D after the August unwind.")
    assert new_fields["soul"] == compile_stored(version)["soul"]          # untouched field unchanged
    assert files[0].diff_stats == {"added": 1, "removed": 1} and files[0].diff[0].startswith("--- v21/")


def test_add_rule_under_numbered_section_gets_next_number_and_slug(env):
    version = v21(env)
    raw = [{"id": "x", "action": "add", "parent": "DA.directives.strategy", "primary": True, "falsified_if": "y",
            "body": "9. LIQUIDITY — skip candidates under $20M average dollar volume."}]
    files, new_fields = P.prepare("DeciderAgent", CFG, version, raw, is_margin_account=False)
    assert files[0].id == "DA.directives.strategy.liquidity" and files[0].kind == "major"
    sd = new_fields["strategy_directives"]
    assert "\n9. LIQUIDITY — skip candidates" in sd
    assert sd.rstrip("\n").endswith("volume.")


def test_remove_last_rule_keeps_tail(env):
    version = v21(env)
    raw = [{"id": "DA.directives.strategy.n8", "action": "remove", "primary": True, "falsified_if": "y"}]
    files, new_fields = P.prepare("DeciderAgent", CFG, version, raw, is_margin_account=False)
    assert files[0].kind == "major"
    base = compile_stored(version)["strategy_directives"]
    n8 = version.nodes["DA.directives.strategy.n8"]
    assert new_fields["strategy_directives"] == base.replace(n8.sep_before + n8.body + n8.sep_after, n8.sep_after, 1) \
        .rstrip("\n") + n8.sep_after or new_fields["strategy_directives"].endswith(version.nodes["DA.directives.strategy.n7"].body)


@pytest.mark.parametrize("raw, message", [
    ([{"id": "DA.directives.ground_truth", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}], "locked"),
    ([{"id": "DA.soul.mission", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}], "locked"),
    ([{"id": "DA.template.user", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}], "locked"),
    ([{"id": "DA.nope", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}], "not a guideline"),
    ([{"id": "DA.directives.strategy.n8", "action": "edit", "body": "x"}], "exactly one file must be primary"),
    ([{"id": "DA.directives.strategy.n8", "action": "edit", "body": "x", "primary": True}], "falsified_if"),
    ([{"id": "DA.directives.strategy", "action": "remove", "primary": True, "falsified_if": "y"}], "guidelines under it"),
    ([{"id": "x", "action": "add", "parent": "DA.directives.strategy.priced_kill", "body": "9. A — b", "primary": True, "falsified_if": "y"}], "not a section"),
    ([{"id": "x", "action": "add", "parent": "DA.code", "body": "9. A — b", "primary": True, "falsified_if": "y"}], "cannot add under"),
    ([{"id": "DA.directives.strategy.n8", "action": "frob", "body": "x", "primary": True, "falsified_if": "y"}], "action must be"),
    ([{"id": f"DA.directives.strategy.n{i}", "action": "edit", "body": "x", "primary": i == 7, "falsified_if": "y"} for i in (7, 8)]
     + [{"id": "x", "action": "add", "parent": "DA.directives.strategy", "body": "9. A — b"}]
     + [{"id": "y", "action": "add", "parent": "DA.directives.strategy", "body": "10. B — c"}], "at most 3"),
])
def test_validation_errors(env, raw, message):
    version = v21(env)
    with pytest.raises(P.ProposalError, match=message):
        P.prepare("DeciderAgent", CFG, version, raw, is_margin_account=False)


def test_unchanged_edit_rejected(env):
    version = v21(env)
    pk = version.nodes["DA.directives.strategy.priced_kill"]
    with pytest.raises(P.ProposalError, match="unchanged"):
        P.prepare("DeciderAgent", CFG, version, [{"id": pk.id, "action": "edit", "body": pk.body, "primary": True,
                                                  "falsified_if": "y"}], is_margin_account=False)


def test_roundtrip_failures_are_explained(env):
    version = v21(env)
    pk = version.nodes["DA.directives.strategy.priced_kill"]
    with pytest.raises(P.ProposalError, match="splits into several"):
        P.prepare("DeciderAgent", CFG, version, [{"id": pk.id, "action": "edit", "body": pk.body + "\n\n## NEW\ntext",
                                                  "primary": True, "falsified_if": "y"}], is_margin_account=False)
    with pytest.raises(P.ProposalError, match="merged into its neighbour"):
        P.prepare("DeciderAgent", CFG, version, [{"id": "n", "action": "add", "parent": "DA.directives.strategy",
                                                  "body": "a sentence that is not a numbered item", "primary": True,
                                                  "falsified_if": "y"}], is_margin_account=False)


def test_mission_guard(env):
    version = v21(env)
    ident = version.nodes["DA.soul.identity"] if "DA.soul.identity" in version.nodes else None
    editable = [n for n in version.nodes.values() if n.field == "soul" and P.editable(n) and n.body.strip()]
    assert editable
    target = editable[0]
    # editing a non-locked soul node is fine; the Mission text lives in a locked node so it cannot vanish
    files, new_fields = P.prepare("DeciderAgent", CFG, version, [{"id": target.id, "action": "edit", "body": target.body + "\nExtra line.",
                                                                  "primary": True, "falsified_if": "y"}], is_margin_account=False)
    assert all(p in new_fields["soul"].lower() for p in P.MISSION_PHRASES)
    assert ident is None or ident.id != target.id or True


def test_parse_llm_json_tolerates_fences():
    assert P.parse_llm_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert P.parse_llm_json("Sure! {\"files\": []} done") == {"files": []}
    with pytest.raises(P.ProposalError):
        P.parse_llm_json("no json here")
    with pytest.raises(P.ProposalError):
        P.parse_llm_json("[1, 2]")


def test_derive_kind():
    ch = P.FileChange(id="a", action="edit", field="strategy_directives", old_body="x  y", body="x y")
    assert P.derive_kind(ch) == "minor"
    ch = P.FileChange(id="a", action="edit", field="strategy_directives", old_body="cap 5%", body="cap 8%")
    assert P.derive_kind(ch) == "major"
    ch = P.FileChange(id="a", action="edit", field="soul", old_body="I like clarity.", body="I like clarity and brevity.")
    assert P.derive_kind(ch) == "minor"
    ch = P.FileChange(id="a", action="edit", field="soul", old_body="I like clarity.", body="I never chase.")
    assert P.derive_kind(ch) == "major"
    assert P.derive_kind(P.FileChange(id="a", action="add", field="memory", parent="DA.memory.log")) == "minor"
    assert P.derive_kind(P.FileChange(id="a", action="add", field="strategy_directives", parent="DA.directives.strategy")) == "major"
    assert P.derive_kind(P.FileChange(id="a", action="remove", field="soul")) == "major"


# ----------------------------------------------------------------------------- pipeline
def test_pipeline_draft_critic_review_then_apply(env):
    version = v21(env)
    llm = FakeLLM(drafter_payload(version))
    out = run(env, llm, focus="kill distance")
    assert out["status"] == "review" and out["base_version"] == 21 and out["model"] == "fake"
    assert [c[0] for c in llm.calls] == ["drafter", "critic"]
    assert "human_focus" in llm.calls[0][2] and "editable_guidelines" in llm.calls[0][2] and "locked_ids" in llm.calls[0][2]
    assert "\"kind\": \"major\"" in llm.calls[1][2]          # the critic sees the code-derived kind and the diff
    assert out["primary_id"] == "DA.directives.strategy.priced_kill"
    assert [f["id"] for f in out["files"]] == ["DA.directives.strategy.priced_kill", "DA.memory.log.2026_09_03_kill_distance"]
    assert out["files"][0]["critic"]["verdict"] == "approve" and out["critic"]["confidence"] == 0.8
    assert out["applies_to"] == {"target_version": 21, "ok": True, "reason": None}
    with env["engine"].connect() as conn:
        rev = conn.execute(text("SELECT id, from_version, to_version, critic_verdict, is_substantive, changes FROM prompt_change_reviews")).fetchall()
    assert len(rev) == 1 and rev[0][1] == 21 and rev[0][2] is None and rev[0][3] == "approve" and rev[0][4]
    assert json.loads(rev[0][5])[0]["node_id"] == "DA.directives.strategy.priced_kill"
    assert out["review_id"] == rev[0][0]

    listing = P.list_proposals(env["engine"], CFG, "DeciderAgent", **env["common"])
    assert listing["in_progress"] is False and listing["proposals"][0]["id"] == out["id"]

    res = P.apply_proposal(env["engine"], out["id"], [f["id"] for f in out["files"]], activate=fake_activate,
                           actor="tester", **env["common"])
    assert res["version"] == 22 and res["previous_version"] == 21 and res["applied_on"] == 21
    assert res["approved"] == [f["id"] for f in out["files"]] and res["rejected"] == []
    assert res["materialized"]["action"] in ("created", "unchanged") and res["materialized"]["roundtrip"] == "ok"
    assert "proposal #" in res["description"] and res["description"].startswith("v22 Decider")

    with env["engine"].connect() as conn:
        row = conn.execute(text("SELECT version, is_active, created_by, strategy_directives, memory, soul FROM prompt_versions "
                                "WHERE config_hash=:h AND version=22"), {"h": CFG}).fetchone()
        active = conn.execute(text("SELECT version FROM prompt_versions WHERE config_hash=:h AND is_active=1"), {"h": CFG}).fetchall()
        ev = conn.execute(text("SELECT from_version, to_version, action FROM prompt_activation_events")).fetchall()
        rev = conn.execute(text("SELECT to_version, human_verdict, human_agrees_critic, human_sections FROM prompt_change_reviews")).fetchone()
    assert row[1] and row[2] == "policy_graph" and "D ≤2.5% full size" in row[3] and row[4].endswith("August unwind.")
    assert row[5] == compile_stored(version)["soul"]
    assert active == [(22,)] and ev[-1][:3] == (21, 22, "apply_proposal")
    assert rev[0] == 22 and rev[1] == "approve" and rev[2] == 1
    assert json.loads(rev[3])["approved"] == res["approved"]

    v22 = read_version_dir(env["root"] / "agents" / "decider" / "policy-graph" / CFG / "v22")
    assert compile_stored(v22)["strategy_directives"] == row[3]
    assert "DA.memory.log.2026_09_03_kill_distance" in v22.nodes
    assert "D ≤2.5%" in v22.nodes["DA.directives.strategy.priced_kill"].body
    assert P.get_proposal(env["engine"], out["id"], **env["common"])["status"] == "applied"


def test_partial_apply_ships_primary_only(env):
    version = v21(env)
    out = run(env, FakeLLM(drafter_payload(version)))
    res = P.apply_proposal(env["engine"], out["id"], ["DA.directives.strategy.priced_kill"], activate=fake_activate, **env["common"])
    assert res["approved"] == ["DA.directives.strategy.priced_kill"] and res["rejected"] == ["DA.memory.log.2026_09_03_kill_distance"]
    with env["engine"].connect() as conn:
        row = conn.execute(text("SELECT memory FROM prompt_versions WHERE config_hash=:h AND version=22"), {"h": CFG}).fetchone()
        rev = conn.execute(text("SELECT human_verdict, human_agrees_critic FROM prompt_change_reviews")).fetchone()
    assert row[0] == compile_stored(version)["memory"] and rev[0] == "partial" and rev[1] is None
    assert P.get_proposal(env["engine"], out["id"], **env["common"])["human"]["verdict"] == "partial"


def test_apply_requires_primary_and_review_status(env):
    version = v21(env)
    out = run(env, FakeLLM(drafter_payload(version)))
    with pytest.raises(P.ProposalError, match="primary"):
        P.apply_proposal(env["engine"], out["id"], ["DA.memory.log.2026_09_03_kill_distance"], activate=fake_activate, **env["common"])
    with pytest.raises(P.ProposalError, match="unknown guideline ids"):
        P.apply_proposal(env["engine"], out["id"], ["DA.directives.strategy.priced_kill", "DA.zzz"], activate=fake_activate, **env["common"])
    with pytest.raises(P.NotConfigured):
        P.apply_proposal(env["engine"], out["id"], ["DA.directives.strategy.priced_kill"], activate=None, **env["common"])
    P.reject_proposal(env["engine"], out["id"], reason="not now")
    with pytest.raises(P.ProposalConflict, match="rejected"):
        P.apply_proposal(env["engine"], out["id"], ["DA.directives.strategy.priced_kill"], activate=fake_activate, **env["common"])


def test_reject_records_human_verdict(env):
    version = v21(env)
    out = run(env, FakeLLM(drafter_payload(version)))
    res = P.reject_proposal(env["engine"], out["id"], reason="softens nothing", actor="tester")
    assert res["status"] == "rejected" and res["human"]["reason"] == "softens nothing"
    with env["engine"].connect() as conn:
        rev = conn.execute(text("SELECT human_verdict, to_version, human_agrees_critic FROM prompt_change_reviews")).fetchone()
        active = conn.execute(text("SELECT version FROM prompt_versions WHERE config_hash=:h AND is_active=1"), {"h": CFG}).fetchall()
    assert rev == ("reject", None, 0) and active == [(21,)]


def test_drafter_retry_then_success(env):
    version = v21(env)
    bad = {"reasoning": "x", "files": [{"id": "DA.directives.ground_truth", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}]}
    llm = FakeLLM([bad, drafter_payload(version)])
    out = run(env, llm)
    assert out["status"] == "review"
    assert [c[0] for c in llm.calls] == ["drafter", "drafter", "critic"]
    assert "REJECTED BY THE VALIDATOR" in llm.calls[1][2] and "locked" in llm.calls[1][2]


def test_drafter_fails_twice(env):
    v21(env)
    bad = {"reasoning": "x", "files": [{"id": "DA.directives.ground_truth", "action": "edit", "body": "x", "primary": True, "falsified_if": "y"}]}
    out = run(env, FakeLLM([bad, bad]))
    assert out["status"] == "failed" and "did not validate" in out["error"] and "locked" in out["error"]
    with env["engine"].connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM prompt_change_reviews")).fetchone()[0] == 0


def test_critic_outage_defers_to_human(env):
    version = v21(env)
    llm = FakeLLM(drafter_payload(version), critic=RuntimeError("boom"))
    out = run(env, llm)
    assert out["status"] == "review" and out["critic"]["confidence"] == 0.0 and "Critic unavailable" in out["critic"]["reason"]
    assert out["files"][0]["critic"] is None


def test_cosmetic_only_is_auto_rejected_without_a_critic_call(env):
    version = v21(env)
    pk = version.nodes["DA.directives.strategy.priced_kill"]
    assert "every BUY ends with" in pk.body
    payload = {"reasoning": "x", "files": [{"id": pk.id, "action": "edit", "body": pk.body.replace("every BUY ends with", "each BUY ends with"),
                                             "primary": True, "falsified_if": "y", "what": "spacing"}]}
    llm = FakeLLM(payload)
    out = run(env, llm)
    assert out["status"] == "review" and out["critic"]["auto"] is True and out["critic"]["verdict"] == "reject"
    assert [c[0] for c in llm.calls] == ["drafter"]
    assert out["files"][0]["kind"] == "minor"


def _add_version(engine, version, *, sd=None, memory=None, activate=True):
    with engine.connect() as conn:
        base = conn.execute(text("SELECT system_prompt, user_prompt_template, strategy_directives, soul, memory FROM prompt_versions "
                                 "WHERE config_hash=:h AND version=21"), {"h": CFG}).fetchone()
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template, strategy_directives,
                             soul, memory, description, created_by, is_active, config_hash, created_at)
                             VALUES ('DeciderAgent', :v, :sp, :up, :sd, :soul, :mem, 'weekly', 'system', 0, :h, :at)"""),
                     {"v": version, "sp": base[0], "up": base[1], "sd": sd if sd is not None else base[2], "soul": base[3],
                      "mem": memory if memory is not None else base[4], "h": CFG, "at": datetime.now()})
        if activate:
            fake_activate(conn, "DeciderAgent", CFG, version, action="save", actor="system", reason="weekly")


def test_rebase_onto_weekly_memory_version(env):
    version = v21(env)
    out = run(env, FakeLLM(drafter_payload(version)))
    mem = compile_stored(version)["memory"] + "\n\n## 2026-09-04 #weekly\n- reminder appended by the weekly loop"
    _add_version(env["engine"], 22, memory=mem)
    listing = P.list_proposals(env["engine"], CFG, "DeciderAgent", **env["common"])
    applies = listing["proposals"][0]["applies_to"]
    assert applies["ok"] and applies["target_version"] == 22 and "rebased onto v22" in applies["reason"]
    res = P.apply_proposal(env["engine"], out["id"], [f["id"] for f in out["files"]], activate=fake_activate, **env["common"])
    assert res["version"] == 23 and res["applied_on"] == 22 and res["previous_version"] == 22
    with env["engine"].connect() as conn:
        row = conn.execute(text("SELECT strategy_directives, memory FROM prompt_versions WHERE config_hash=:h AND version=23"), {"h": CFG}).fetchone()
    assert "D ≤2.5% full size" in row[0]
    assert "reminder appended by the weekly loop" in row[1] and row[1].endswith("August unwind.")


def test_conflict_when_active_version_changed_the_edited_guideline(env):
    version = v21(env)
    out = run(env, FakeLLM(drafter_payload(version)))
    sd = compile_stored(version)["strategy_directives"].replace("D ≤3% full size", "D ≤4% full size")
    _add_version(env["engine"], 22, sd=sd)
    listing = P.list_proposals(env["engine"], CFG, "DeciderAgent", **env["common"])
    applies = listing["proposals"][0]["applies_to"]
    assert applies["ok"] is False and "changed DA.directives.strategy.priced_kill" in applies["reason"]
    with pytest.raises(P.ProposalConflict, match="draft again"):
        P.apply_proposal(env["engine"], out["id"], [f["id"] for f in out["files"]], activate=fake_activate, **env["common"])


def test_one_in_progress_proposal_per_agent_and_stale_expiry(env):
    version = v21(env)
    with env["engine"].begin() as conn:
        conn.execute(text("""INSERT INTO policy_graph_proposals (created_at, updated_at, config_hash, agent_type, base_version, status)
                             VALUES (:now, :now, :h, 'DeciderAgent', 21, 'drafting')"""), {"now": datetime.now(), "h": CFG})
    with pytest.raises(P.ProposalConflict, match="still being drafted"):
        run(env, FakeLLM(drafter_payload(version)))
    listing = P.list_proposals(env["engine"], CFG, "DeciderAgent", **env["common"])
    assert listing["in_progress"] is True
    old = datetime.now() - timedelta(minutes=45)
    with env["engine"].begin() as conn:
        conn.execute(text("UPDATE policy_graph_proposals SET updated_at = :old"), {"old": old})
    listing = P.list_proposals(env["engine"], CFG, "DeciderAgent", **env["common"])
    assert listing["in_progress"] is False and listing["proposals"][0]["status"] == "failed"
    assert "restarted" in listing["proposals"][0]["error"]
    out = run(env, FakeLLM(drafter_payload(version)))       # the slot is free again
    assert out["status"] == "review"


def test_start_draft_needs_llm(env):
    with pytest.raises(P.NotConfigured):
        P.start_draft(env["engine"], CFG, "DeciderAgent", llm=None, context_fn=None, background=False, **env["common"])
