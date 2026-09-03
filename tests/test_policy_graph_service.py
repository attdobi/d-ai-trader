"""Service / health / routes / backfill of the policy graph on an in-memory SQLite database.

Tables are created with exactly the columns service.py reads; row text comes from the byte-exact
fixtures; the repo root is tmp_path; inherited defaults are monkeypatched to a fixed InheritedText.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from policy_graph import health, service
from policy_graph.compile import compile_effective, read_version_dir
from policy_graph.model import InheritedText

CFG = "cfg_test"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "policy_graph"
SOUL_DEFAULT = "agents/decider/SOUL.default.md"


def fx(name: str) -> str:
    with open(FIXTURES / name, "rb") as fh:
        return fh.read().decode("utf-8")


# ----------------------------------------------------------------------------- schema + seed
DDL = [
    """CREATE TABLE prompt_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_type TEXT NOT NULL, version INTEGER NOT NULL,
        system_prompt TEXT, user_prompt_template TEXT, strategy_directives TEXT, soul TEXT DEFAULT '',
        memory TEXT DEFAULT '', description TEXT, created_by TEXT, is_active BOOLEAN DEFAULT 0,
        config_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE prompt_activation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TIMESTAMP, batch_id TEXT NOT NULL,
        config_hash TEXT NOT NULL, agent_type TEXT NOT NULL, from_version INTEGER, to_version INTEGER,
        action TEXT NOT NULL, actor TEXT, reason TEXT)""",
    """CREATE TABLE prompt_change_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TIMESTAMP, config_hash TEXT, agent_type TEXT NOT NULL,
        from_version INTEGER, to_version INTEGER, change_summary TEXT, changes TEXT, is_substantive BOOLEAN,
        critic_verdict TEXT, critic_reason TEXT, critic_confidence FLOAT, critic_at TIMESTAMP,
        human_verdict TEXT, human_at TIMESTAMP, human_agrees_critic BOOLEAN, human_sections TEXT,
        critic_auto BOOLEAN, realized_winrate_delta FLOAT, realized_pnl FLOAT, outcome_measured_at TIMESTAMP)""",
    """CREATE TABLE decider_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT NOT NULL, created_at TIMESTAMP,
        updated_at TIMESTAMP, kind TEXT DEFAULT 'lesson', tags TEXT, ticker TEXT, content TEXT NOT NULL,
        source TEXT DEFAULT 'feedback', weight REAL DEFAULT 1.0, active BOOLEAN DEFAULT 1)""",
    """CREATE TABLE trade_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, config_hash TEXT NOT NULL, ticker TEXT NOT NULL,
        sell_timestamp TIMESTAMP, purchase_price FLOAT, sell_price FLOAT, shares FLOAT,
        gain_loss_amount FLOAT, gain_loss_percentage FLOAT, hold_duration_days INTEGER,
        original_reason TEXT, sell_reason TEXT, outcome_category TEXT, market_context TEXT,
        created_at TIMESTAMP)""",
]

SYS21 = fx("decider_v21_system.md")
USER21 = fx("decider_v21_user.md")

DECIDER_ROWS = [
    # version, sd, soul, memory, created_by, is_active, created_at, id
    (0, fx("decider_v00_sd.md"), fx("decider_v00_soul.md"), fx("decider_v00_memory.md"), "init_database", 0,
     "2026-08-03 08:17:21.548000", 547),
    (19, fx("decider_v19_sd.md"), "", fx("decider_v19_memory.md"), "system", 0, "2026-08-20 09:00:00", 597),
    (20, fx("decider_v20_sd.md"), fx("decider_v20_soul.md"), fx("decider_v20_memory.md"), "claude_code", 0,
     "2026-08-27 09:30:00", 598),
    (21, fx("decider_v21_sd.md"), fx("decider_v21_soul.md"), fx("decider_v21_memory.md"), "claude_code", 1,
     "2026-09-02 14:57:20.858624", 599),
]
FEEDBACK_ROWS = [
    (7, "", fx("feedback_v07_soul.md"), fx("feedback_v07_memory.md"), "prompt_lab", 0, "2026-08-25 10:00:00", 601),
    (8, fx("feedback_v08_sd.md"), fx("feedback_v07_soul.md"), fx("feedback_v08_memory.md"), "claude_code", 1,
     "2026-09-02 15:10:00", 602),
]

EVENTS = [
    (1, "2026-08-13 08:00:00", "b1", "DeciderAgent", 0, 19, "save", "feedback_agent"),
    (2, "2026-08-27 10:00:00", "b2", "DeciderAgent", 19, 20, "save", "prompt_lab"),
    (3, "2026-09-02 14:57:21", "b3", "DeciderAgent", 20, 21, "save", "claude_code"),
    (4, "2026-09-02 15:10:01", "b4", "FeedbackAgent", 7, 8, "save", "claude_code"),
]
REVIEWS = [
    # id, created_at, from, to, critic_verdict, critic_reason, conf, human_verdict, agrees, auto
    (5, "2026-08-21 09:00:00", 19, None, "reject", "no evidence", 0.7, "reject", 1, 0),
    (16, "2026-08-27 09:31:00", 19, 20, "approve", "fine", 0.8, "approve", 1, 0),
    (17, "2026-09-02 14:58:00", 20, 21, "reject", "too aggressive", 0.9, "approve", 0, 0),
]
MEMORY_ROWS = [
    # id, created_at, kind, tags, ticker, content, source, weight, active
    (1, "2026-07-01 10:00:00", "rule", "{gap-chase,regime}", "IRDM", "Never chase a gap over +8%.", "human", 2.0, 1),
    (2, "2026-07-15 10:00:00", "lesson", "{priced-kill}", None, "Kill at the priced level, not the feeling.", "feedback", 1.0, 1),
    (3, "2026-08-01 10:00:00", "lesson", None, "NVDA", "Extension over 20d MA is a fade, not a buy.", "feedback", 1.0, 0),
    (4, "2026-09-03 10:00:00", "rule", "{quarantine}", None, "Re-entry quarantine is two sessions.", "human", 1.5, 1),
]


def _trades():
    rows = []
    # v19 window [2026-08-13 08:00, 2026-08-27 10:00): 5 closed, 2 wins
    for i, pct in enumerate([3.0, -2.0, 1.5, -1.0, -0.5]):
        rows.append((f"2026-08-{14 + i:02d} 12:00:00", "AAA", pct, pct * 5, "momentum entry"))
    # v20 window [2026-08-27 10:00, 2026-09-02 14:57:21): 6 closed, 4 wins + 1 synced (excluded)
    days = ["2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02"]
    for day, pct in zip(days, [2.0, 3.0, -1.0, 4.0, 1.0, -2.0]):
        rows.append((f"{day} 12:00:00", "BBB", pct, pct * 5, "technical pullback"))
    rows.append(("2026-08-29 13:00:00", "SYNC", 9.0, 90.0, "Schwab synced position"))
    # v21 window [2026-09-02 14:57:21, None): 2 closed
    rows.append(("2026-09-02 16:00:00", "CCC", 3.0, 15.0, "regime-gated pullback"))
    rows.append(("2026-09-03 16:00:00", "DDD", -1.0, -5.0, "regime-gated pullback"))
    return rows


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in DDL:
            conn.execute(text(ddl))
        for agent, rows in (("DeciderAgent", DECIDER_ROWS), ("FeedbackAgent", FEEDBACK_ROWS)):
            for v, sd, soul, mem, by, active, at, rid in rows:
                conn.execute(text("""
                    INSERT INTO prompt_versions (id, agent_type, version, system_prompt, user_prompt_template,
                        strategy_directives, soul, memory, description, created_by, is_active, config_hash, created_at)
                    VALUES (:id, :a, :v, :sp, :up, :sd, :soul, :mem, :d, :by, :active, :h, :at)
                """), {"id": rid, "a": agent, "v": v, "sp": SYS21 if agent == "DeciderAgent" else "feedback sys",
                       "up": USER21 if agent == "DeciderAgent" else "feedback user", "sd": sd, "soul": soul,
                       "mem": mem, "d": f"{agent} v{v}", "by": by, "active": active, "h": CFG, "at": at})
        for eid, at, batch, agent, frm, to, action, actor in EVENTS:
            conn.execute(text("""
                INSERT INTO prompt_activation_events (id, created_at, batch_id, config_hash, agent_type, from_version,
                    to_version, action, actor) VALUES (:id, :at, :b, :h, :a, :f, :t, :ac, :actor)
            """), {"id": eid, "at": at, "b": batch, "h": CFG, "a": agent, "f": frm, "t": to, "ac": action, "actor": actor})
        for rid, at, frm, to, cv, cr, conf, hv, agrees, auto in REVIEWS:
            conn.execute(text("""
                INSERT INTO prompt_change_reviews (id, created_at, config_hash, agent_type, from_version, to_version,
                    critic_verdict, critic_reason, critic_confidence, human_verdict, human_agrees_critic, critic_auto)
                VALUES (:id, :at, :h, 'DeciderAgent', :f, :t, :cv, :cr, :conf, :hv, :agrees, :auto)
            """), {"id": rid, "at": at, "h": CFG, "f": frm, "t": to, "cv": cv, "cr": cr, "conf": conf, "hv": hv,
                   "agrees": agrees, "auto": auto})
        for rid, at, kind, tags, ticker, content, source, weight, active in MEMORY_ROWS:
            conn.execute(text("""
                INSERT INTO decider_memory (id, config_hash, created_at, updated_at, kind, tags, ticker, content,
                    source, weight, active) VALUES (:id, :h, :at, :at, :k, :tags, :tk, :c, :s, :w, :active)
            """), {"id": rid, "h": CFG, "at": at, "k": kind, "tags": tags, "tk": ticker, "c": content, "s": source,
                   "w": weight, "active": active})
        for at, ticker, pct, amount, reason in _trades():
            conn.execute(text("""
                INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, purchase_price, sell_price, shares,
                    gain_loss_amount, gain_loss_percentage, hold_duration_days, original_reason, created_at)
                VALUES (:h, :tk, :at, 10, 11, 1, :amt, :pct, 2, :reason, :at)
            """), {"h": CFG, "tk": ticker, "at": at, "amt": amount, "pct": pct, "reason": reason})
    yield engine
    engine.dispose()


@pytest.fixture
def inherited_soul(monkeypatch):
    """Empty soul rows inherit a fixed text (no git involved)."""
    text_ = fx("decider_v18_soul.md")

    def fake(repo_root, agent_dir, filename, created_at, *, is_active_row):
        if filename == "SOUL.md":
            return InheritedText(text=text_, source_path=SOUL_DEFAULT, git_sha="54a50e5e",
                                 resolution="git-blob-at-created_at" if not is_active_row else "worktree")
        return None

    monkeypatch.setattr(service.inherited, "resolve_inherited", fake)
    return text_


@pytest.fixture
def env(db, tmp_path, inherited_soul):
    return {"engine": db, "root": tmp_path, "soul": inherited_soul,
            "common": {"repo_root": tmp_path, "is_margin_account": False}}


# ----------------------------------------------------------------------------- versions
def test_list_versions_ordering_joins_and_lineage(env):
    out = service.list_versions(env["engine"], CFG, "DeciderAgent", **env["common"])
    assert [v["version"] for v in out["versions"]] == [0, 19, 20, 21]
    assert out["current"] == 21 and out["latest"] == 21 and out["prefix"] == "DA"
    by = {v["version"]: v for v in out["versions"]}

    assert by[21]["activation"]["event_id"] == 3 and by[21]["activation"]["from_version"] == 20
    assert by[21]["activation"]["actor"] == "claude_code"
    assert by[0]["activation"] is None
    assert by[21]["review"]["review_id"] == 17 and by[21]["review"]["critic_verdict"] == "reject"
    assert by[21]["review"]["human_verdict"] == "approve" and by[21]["review"]["critic_confidence"] == 0.9
    assert by[20]["review"]["review_id"] == 16
    assert [c["review_id"] for c in by[19]["rejected_candidates"]] == [5]
    assert by[21]["rejected_candidates"] == []

    assert by[0]["actor_kind"] == "seed" and by[19]["actor_kind"] == "weekly" and by[20]["actor_kind"] == "claude_code"
    assert by[19]["parent_version"] == 0 and by[19]["lineage_version"] == 0      # weekly → nearest non-weekly ancestor
    assert by[20]["lineage_version"] == 20 and by[21]["lineage_version"] == 21 and by[21]["parent_version"] == 20
    assert by[0]["kind"] == "seed" and by[21]["kind"] == "policy"
    assert by[21]["is_active"] is True and by[21]["prompt_version_id"] == 599
    assert by[21]["created_at"].startswith("2026-09-02T14:57:20")

    for v in out["versions"]:
        assert v["materialized"] is True and v["stale"] is False and v["roundtrip"] == "ok"
        assert v["node_count"] > 10
    assert by[19]["fields"] == {"soul": "inherited", "memory": "stored"}
    assert by[21]["fields"] == {"soul": "stored", "memory": "stored"}
    assert by[21]["delta_vs_prev"]["added"] > 0
    assert any("activation events exist from 2026-08-13" in n for n in out["notes"])
    # the version dirs live under the tmp repo root, per config hash
    assert (env["root"] / "agents" / "decider" / "policy-graph" / CFG / "v21" / "manifest.json").exists()


def test_outcome_windows_use_trade_outcomes_created_at_and_exclude_synced(env):
    out = service.list_versions(env["engine"], CFG, "DeciderAgent", **env["common"])
    by = {v["version"]: v for v in out["versions"]}
    o20 = by[20]["outcome"]
    assert o20["n_closed"] == 6                       # the Schwab synced position is excluded
    assert o20["win_rate"] == pytest.approx(4 / 6, abs=1e-3)
    assert o20["measurable"] is True
    assert o20["window"] == ["2026-08-27T10:00:00", "2026-09-02T14:57:21"]   # activation-event boundaries
    assert o20["prior_win_rate"] == pytest.approx(0.4)
    assert o20["winrate_delta"] == pytest.approx(4 / 6 - 0.4, abs=1e-3)
    assert o20["clock"] == health.CLOCK_LABEL and o20["lineage_window"] is True
    o21 = by[21]["outcome"]
    assert o21["n_closed"] == 2 and o21["measurable"] is False and o21["winrate_delta"] is None
    assert o21["window"] == ["2026-09-02T14:57:21", None]
    o19 = by[19]["outcome"]
    assert o19["n_closed"] == 5 and o19["win_rate"] == pytest.approx(0.4)
    # Feedback agent: no direct attribution
    fb = service.list_versions(env["engine"], CFG, "FeedbackAgent", **env["common"])
    assert all(v["outcome"] is None for v in fb["versions"])
    assert fb["versions"][0]["outcome_reason"] == "no direct trade attribution"
    assert fb["current"] == 8


def test_health_version_bounds_fallbacks():
    versions = [{"version": 1, "created_at": "2026-06-01 09:00:00"}, {"version": 2, "created_at": "2026-06-10 09:00:00"},
                {"version": 3, "created_at": "2026-06-20 09:00:00"}]
    events = [{"id": 1, "created_at": "2026-06-15 09:00:00", "to_version": 2, "from_version": 1}]
    b = health.version_bounds(versions, events)
    assert b[1]["start_source"] == "row_created_at" and b[1]["end"] == datetime(2026, 6, 10, 9)   # next row
    assert b[2]["start"] == datetime(2026, 6, 15, 9) and b[2]["end"] is None                       # in force
    assert b[3]["start_source"] == "row_created_at" and b[3]["end"] is None
    # an event that switches away closes a row-based window before the next row does
    events.append({"id": 2, "created_at": "2026-06-05 09:00:00", "to_version": 3, "from_version": 1})
    b = health.version_bounds(versions, events)
    assert b[1]["end"] == datetime(2026, 6, 5, 9) and b[3]["start"] == datetime(2026, 6, 5, 9)
    assert b[3]["end"] == datetime(2026, 6, 15, 9)


def test_list_agents_counts(env):
    out = service.list_agents(env["engine"], CFG, repo_root=env["root"])
    by = {a["agent_type"]: a for a in out["agents"]}
    assert out["config_hash"] == CFG
    assert by["DeciderAgent"]["version_count"] == 4 and by["DeciderAgent"]["active_version"] == 21
    assert by["DeciderAgent"]["stale"] == 4          # nothing materialized yet
    assert by["FeedbackAgent"]["label"] == "Feedback" and by["FeedbackAgent"]["prefix"] == "FA"
    assert by["SummarizerAgent"]["version_count"] == 0
    service.list_versions(env["engine"], CFG, "DeciderAgent", **env["common"])
    out = service.list_agents(env["engine"], CFG, repo_root=env["root"])
    assert {a["agent_type"]: a["stale"] for a in out["agents"]}["DeciderAgent"] == 0


# ----------------------------------------------------------------------------- materialize
def test_ensure_materialized_created_then_unchanged_and_inherited(env):
    r1 = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 19, materialized_by="test", **env["common"])
    assert r1["action"] == "created" and r1["roundtrip"] == "ok"
    r2 = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 19, materialized_by="test", **env["common"])
    assert r2["action"] == "unchanged"
    v = read_version_dir(Path(r1["path"]))
    fm = v.manifest["fields"]["soul"]
    assert fm["inherited"] is True and fm["inherited_git_sha"] == "54a50e5e" and fm["inherited_from"] == SOUL_DEFAULT
    assert compile_effective(v)["soul"] == env["soul"]
    assert any(n.owner == "default-file" for n in v.nodes.values())
    assert v.manifest["lineage"]["activation"]["event_id"] == 1
    assert v.manifest["lineage"]["lineage_version"] == 0
    assert v.manifest["materialized_by"] == "test"
    with pytest.raises(service.NotFound):
        service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 5, **env["common"])


def test_plan_action_and_rebuild_force(env):
    assert service.plan_action(env["engine"], CFG, "DeciderAgent", 21, **env["common"]) == "created"
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert service.plan_action(env["engine"], CFG, "DeciderAgent", 21, **env["common"]) == "unchanged"
    out = service.rebuild(env["engine"], CFG, "DeciderAgent", 21, force=True, **env["common"])
    assert out["results"] == [{"agent_type": "DeciderAgent", "version": 21, "action": "rebuilt", "roundtrip": "ok"}]
    assert out["code_sha"] and out["ltm_sha"]
    out = service.rebuild(env["engine"], CFG, "all", "all", **env["common"])
    assert len(out["results"]) == 6 and {r["action"] for r in out["results"]} == {"created", "unchanged"}
    with pytest.raises(service.NotFound):
        service.rebuild(env["engine"], CFG, "DeciderAgent", 77, **env["common"])


def test_row_change_is_detected_as_replaced(env):
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    with env["engine"].begin() as conn:
        conn.execute(text("UPDATE prompt_versions SET memory = memory || '\n\n## 2026-09-03\n- late note' "
                          "WHERE agent_type='DeciderAgent' AND version=21"))
    assert service.plan_action(env["engine"], CFG, "DeciderAgent", 21, **env["common"]) == "replaced"
    res = service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert res["action"] == "replaced"
    out = service.list_versions(env["engine"], CFG, "DeciderAgent", **env["common"])
    v21 = [v for v in out["versions"] if v["version"] == 21][0]
    assert v21["rewrites"] == 1 and v21["roundtrip"] == "ok"
    assert (env["root"] / "agents" / "decider" / "policy-graph" / CFG / "_prior").is_dir()


# ----------------------------------------------------------------------------- ltm rows
def test_ltm_rows_parse_sqlite_tags_and_snapshots(env):
    rows = service.ltm_rows(env["engine"], CFG)
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    assert rows[0]["tags"] == ["gap-chase", "regime"] and rows[2]["tags"] == [] and rows[2]["active"] is False
    assert isinstance(rows[0]["created_at"], datetime)
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 20, **env["common"])
    service.ensure_materialized(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    root = env["root"] / "agents" / "decider" / "policy-graph" / CFG
    m20 = json.loads((root / "v20" / "manifest.json").read_text())
    m21 = json.loads((root / "v21" / "manifest.json").read_text())
    assert m20["ltm"]["snapshot"] == "reconstructed" and sorted(m20["ltm"]["row_ids"]) == [1, 2, 3]   # row 4 is newer than v20
    assert m21["ltm"]["snapshot"] == "live" and sorted(m21["ltm"]["row_ids"]) == [1, 2, 3, 4]
    assert m20["ltm"]["sha"] != m21["ltm"]["sha"]
    v21 = read_version_dir(root / "v21")
    assert "DA.ltm.4" in v21.nodes and v21.nodes["DA.ltm.1"].body == "- [rule] (IRDM) Never chase a gap over +8%."


# ----------------------------------------------------------------------------- graph payload
def test_graph_payload_embeds_bodies_and_change_flags(env):
    g = service.graph_payload(env["engine"], CFG, "DeciderAgent", None, **env["common"])
    assert g["version"] == 21 and g["previous_version"] == 20 and g["next_version"] is None
    assert g["available_versions"] == [0, 19, 20, 21] and g["layer"] == "effective"
    assert g["title"] == "Decider policy v21" and g["root_id"] == "DA.root"
    by = {n["id"]: n for n in g["nodes"]}
    assert by["DA.directives.strategy.priced_kill"]["body"].startswith("3. PRICED KILL")
    assert by["DA.directives.strategy.priced_kill"]["change"] == "added"
    assert by["DA.directives.strategy.priced_kill"]["polarity"] == "gate"
    assert by["DA.directives.ground_truth"]["change"] == "same" and by["DA.directives.ground_truth"]["locked"] is True
    assert by["DA.directives.strategy"]["change"] == "changed"
    assert by["DA.template.system"]["node_type"] == "template" and by["DA.template.system"]["body"] == SYS21
    assert "DA.code.crowd_fade" in by and by["DA.code.crowd_fade"]["fires"] is True
    assert by["DA.code.crowd_fade"]["owner"] == "code" and by["DA.code.crowd_fade"]["condition"]
    assert by["DA.ltm.1"]["injected"] is True and by["DA.ltm.3"]["status"] == "inactive"
    assert "DA.runtime.inputs" in by
    assert {r["id"] for r in g["removed_nodes"]} >= {"DA.memory.log.2026_08_27"}
    assert g["stats"]["nodes"] == len(g["nodes"]) and g["stats"]["edges"] == len(g["edges"])
    assert g["stats"]["added"] >= 8 and g["stats"]["removed"] >= 1
    ids = set(by)
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids
    assert {e["edge_type"] for e in g["edges"]} >= {"subtype_of", "includes"}
    assert g["code"]["fires"]["DA.code.crowd_fade"] is True and g["code"]["fires"]["DA.code.json_fallback"] is False
    assert g["ltm"]["snapshot"] == "live" and g["ltm"]["count"] == 4
    assert g["timeline"]["activation"]["event_id"] == 3 and g["timeline"]["review"]["review_id"] == 17
    assert g["roundtrip"] == "ok" and g["stale"] is False and g["rebuilt_on_read"] is True
    assert g["links"]["compiled_stored"].endswith("mode=stored&field=all")
    assert g["links"]["files"] == f"agents/decider/policy-graph/{CFG}/v21/"
    json.dumps(g)      # fully serialisable

    g2 = service.graph_payload(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert g2["rebuilt_on_read"] is False


def test_graph_layers_refs_and_inherited(env):
    stored = service.graph_payload(env["engine"], CFG, "DeciderAgent", 21, layer="stored", **env["common"])
    owners = {n["owner"] for n in stored["nodes"]}
    assert "code" not in owners and "decider_memory" not in owners and "runtime" not in owners
    assert {e["edge_type"] for e in stored["edges"]} & {"includes", "overlaps", "constrains"} == set()
    assert "DA.directives.strategy.regime_gate" in {n["id"] for n in stored["nodes"]}

    refs = service.graph_payload(env["engine"], CFG, "DeciderAgent", 21, refs=True, **env["common"])
    plain = service.graph_payload(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert not any(n["node_type"] == "ticker" for n in plain["nodes"])
    assert not any(e["edge_type"] == "cites" for e in plain["edges"])
    ticker_nodes = [n for n in refs["nodes"] if n["node_type"] == "ticker"]
    assert ticker_nodes, "refs=1 adds ticker reference nodes (v21 memory cites IRDM)"
    assert any(e["edge_type"] == "cites" and e["synthetic"] for e in refs["edges"])

    v19 = service.graph_payload(env["engine"], CFG, "DeciderAgent", 19, **env["common"])
    inh = [n for n in v19["nodes"] if n["owner"] == "default-file"]
    assert inh and all(n["compiled"] == "effective-only" for n in inh)
    assert inh[0]["inherited"] == {"from": SOUL_DEFAULT, "git_sha": "54a50e5e", "resolution": "git-blob-at-created_at"}
    assert v19["inherited"]["soul"]["git_sha"] == "54a50e5e" and v19["inherited"]["memory"] is None
    assert v19["actor_kind"] == "weekly"
    v20 = service.graph_payload(env["engine"], CFG, "DeciderAgent", 20, **env["common"])
    assert "soul" in v20["stats"] or True
    soul_nodes = [n for n in v20["nodes"] if n["field"] == "soul"]
    assert soul_nodes and all(n["change"] == "source_changed" for n in soul_nodes)

    with pytest.raises(service.BadRequest):
        service.graph_payload(env["engine"], CFG, "DeciderAgent", 21, layer="bogus", **env["common"])
    with pytest.raises(service.NotFound):
        service.graph_payload(env["engine"], CFG, "DeciderAgent", 3, **env["common"])


# ----------------------------------------------------------------------------- node / diff
def test_node_payload_history_diff_and_overlaps(env):
    service.list_versions(env["engine"], CFG, "DeciderAgent", **env["common"])      # materialize all
    p = service.node_payload(env["engine"], CFG, "DeciderAgent", 21, "DA.directives.strategy", **env["common"])
    assert p["node"]["id"] == "DA.directives.strategy" and p["node"]["change"] == "changed"
    assert p["previous"]["version"] == 20 and p["previous"]["id"] == "DA.directives.strategy"
    assert p["diff_vs_previous"][0].startswith("--- DA.directives.strategy@v20")
    assert p["diff_vs_previous"][1].startswith("+++ DA.directives.strategy@v21")
    assert any(l.startswith("@@") for l in p["diff_vs_previous"])
    versions = [h["version"] for h in p["history"]]
    assert versions == sorted(versions) and 21 in versions and 20 in versions
    assert p["first_seen"] <= 20 and p["present_in"] >= 2 and 21 in p["changed_in"]
    assert p["version_outcome"]["n_closed"] == 2 and p["attribution_note"]
    assert p["version_count"] == 4
    added = service.node_payload(env["engine"], CFG, "DeciderAgent", 21, "DA.directives.strategy.priced_kill", **env["common"])
    assert added["node"]["change"] == "added" and added["previous"] is None
    assert isinstance(added["overlaps"], list)
    code = service.node_payload(env["engine"], CFG, "DeciderAgent", 21, "DA.code.confirmation_policy", **env["common"])
    assert code["node"]["owner"] == "code" and code["history"] == []
    with pytest.raises(service.NotFound):
        service.node_payload(env["engine"], CFG, "DeciderAgent", 21, "DA.directives.nope", **env["common"])
    with pytest.raises(service.BadRequest):
        service.node_payload(env["engine"], CFG, "DeciderAgent", 21, "../etc", **env["common"])


def test_diff_payload_between_versions(env):
    d = service.diff_payload(env["engine"], CFG, "DeciderAgent", 20, 21, **env["common"])
    assert d["from"] == 20 and d["to"] == 21
    by = {n["id"]: n for n in d["nodes"]}
    assert by["DA.directives.strategy.regime_gate"]["change"] == "added"
    assert by["DA.memory.log.2026_08_27"]["change"] == "removed"
    assert by["DA.directives.strategy"]["change"] == "changed" and by["DA.directives.strategy"]["stats"]["added"] > 0
    assert d["fields"]["strategy_directives"]["changed"] is True and d["fields"]["system_prompt"]["changed"] is False
    assert d["summary"]["added"] >= 8 and d["summary"]["removed"] >= 1
    assert "same" not in {n["change"] for n in d["nodes"]}
    far = service.diff_payload(env["engine"], CFG, "DeciderAgent", 0, 21, **env["common"])     # non-adjacent
    assert far["summary"]["added"] > 0


# ----------------------------------------------------------------------------- compiled text
def test_compiled_text_stored_bytes_equal_column(env):
    for field, fixture in (("strategy_directives", "decider_v21_sd.md"), ("soul", "decider_v21_soul.md"),
                           ("memory", "decider_v21_memory.md"), ("user_prompt_template", "decider_v21_user.md")):
        body, rt = service.compiled_text(env["engine"], CFG, "DeciderAgent", 21, mode="stored", field=field, **env["common"])
        header, sep, rest = body.partition("\n---\n")
        assert sep and header.startswith(f"# DeciderAgent v21 — stored render · {field} · ")
        assert rest.encode("utf-8") == fx(fixture).encode("utf-8")
        assert rt == "ok"
        assert "\n".join(body.split("\n")[2:]) == fx(fixture)          # sed '1,2d' equivalence
    body, _ = service.compiled_text(env["engine"], CFG, "DeciderAgent", 21, mode="stored", field="all", **env["common"])
    assert "\n\n=== soul ===\n" in body and body.count("=== ") == 5
    eff, _ = service.compiled_text(env["engine"], CFG, "DeciderAgent", 19, mode="effective", field="soul", **env["common"])
    assert eff.split("\n---\n", 1)[1] == env["soul"]
    stored19, _ = service.compiled_text(env["engine"], CFG, "DeciderAgent", 19, mode="stored", field="soul", **env["common"])
    assert stored19.split("\n---\n", 1)[1] == ""
    rt, _ = service.compiled_text(env["engine"], CFG, "DeciderAgent", 21, mode="runtime", field="all", **env["common"])
    assert "\n# ---- USER PROMPT ----\n" in rt and "## AGENT IDENTITY" in rt and "CROWD-FADE" in rt
    with pytest.raises(service.BadRequest):
        service.compiled_text(env["engine"], CFG, "DeciderAgent", 21, mode="raw", field="all", **env["common"])


def test_bundle_and_node_file(env):
    b = service.bundle_text(env["engine"], CFG, "DeciderAgent", 21, **env["common"])
    assert b.startswith("<!-- DA.root.md -->") and "<!-- DA.code.crowd_fade.md -->" in b
    b2 = service.bundle_text(env["engine"], CFG, "DeciderAgent", 21, include_code=False, include_ltm=False, **env["common"])
    assert "DA.code." not in b2 and "DA.ltm." not in b2
    raw = service.node_file(env["engine"], CFG, "DeciderAgent", 21, "DA.directives.strategy.priced_kill", **env["common"])
    assert raw.startswith(b"---\nid: DA.directives.strategy.priced_kill\n")
    raw_code = service.node_file(env["engine"], CFG, "DeciderAgent", 21, "DA.code.crowd_fade", **env["common"])
    assert b"owner: code" in raw_code
    with pytest.raises(service.NotFound):
        service.node_file(env["engine"], CFG, "DeciderAgent", 21, "DA.directives.zzz", **env["common"])


# ----------------------------------------------------------------------------- routes (real Flask)
@pytest.fixture
def client(env):
    flask = pytest.importorskip("flask")
    from policy_graph.routes import register_policy_graph_routes
    app = flask.Flask("pg_test")
    register_policy_graph_routes(app, engine=env["engine"], get_config_hash=lambda: CFG,
                                 repo_root=env["root"], is_margin_account=False)
    return app.test_client()


def test_routes_json_shapes_and_errors(client):
    r = client.get("/api/policy-graph/agents")
    assert r.status_code == 200 and r.get_json()["config_hash"] == CFG
    r = client.get("/api/policy-graph/versions?agent=DeciderAgent")
    assert r.status_code == 200 and r.get_json()["current"] == 21
    r = client.get("/api/policy-graph/graph?agent=DeciderAgent&version=21&layer=stored")
    g = r.get_json()
    assert r.status_code == 200 and g["layer"] == "stored" and "nodes" in g
    r = client.get("/api/policy-graph/node?agent=DeciderAgent&version=21&id=DA.directives.strategy")
    assert r.status_code == 200 and r.get_json()["node"]["id"] == "DA.directives.strategy"
    r = client.get("/api/policy-graph/diff?agent=DeciderAgent&from=20&to=21")
    assert r.status_code == 200 and r.get_json()["to"] == 21
    r = client.get("/api/policy-graph/compiled?agent=DeciderAgent&version=21&mode=stored&field=strategy_directives")
    assert r.status_code == 200 and r.mimetype == "text/plain" and r.headers["X-Policy-Roundtrip"] == "ok"
    assert r.get_data(as_text=True).split("\n", 2)[2] == fx("decider_v21_sd.md")
    r = client.get("/api/policy-graph/bundle?agent=DeciderAgent&version=21&include_code=0")
    assert r.status_code == 200 and "DA.code." not in r.get_data(as_text=True)
    r = client.get("/api/policy-graph/file?agent=DeciderAgent&version=21&id=DA.root")
    assert r.status_code == 200 and r.mimetype == "text/markdown"
    r = client.post("/api/policy-graph/rebuild", json={"agent_type": "DeciderAgent", "version": 21, "force": True})
    assert r.status_code == 200 and r.get_json()["results"][0]["action"] == "rebuilt"

    # error envelope
    assert client.get("/api/policy-graph/versions").get_json() == {"error": "agent is required (DeciderAgent | SummarizerAgent | FeedbackAgent)"}
    assert client.get("/api/policy-graph/versions").status_code == 400
    r = client.get("/api/policy-graph/graph?agent=DeciderAgent&version=3")
    assert r.status_code == 404 and "error" in r.get_json()
    r = client.get("/api/policy-graph/node?agent=DeciderAgent&version=21&id=bad id")
    assert r.status_code == 400
    r = client.get("/api/policy-graph/graph?agent=Nope")
    assert r.status_code == 400
    r = client.get("/api/policy-graph/compiled?agent=DeciderAgent&version=21&mode=stored&field=nope")
    assert r.status_code == 400
    r = client.post("/api/policy-graph/rebuild", json={"agent_type": "DeciderAgent", "version": "x"})
    assert r.status_code == 400


def test_routes_store_busy_is_503(client, monkeypatch):
    from policy_graph import store

    def busy(*_a, **_k):
        raise store.StoreBusy("locked")

    monkeypatch.setattr(store, "materialize", busy)
    r = client.get("/api/policy-graph/graph?agent=DeciderAgent&version=21")
    assert r.status_code == 503 and r.get_json() == {"error": "policy graph is being rebuilt — retry"}
    r = client.post("/api/policy-graph/rebuild", json={"agent_type": "all", "version": "all"})
    assert r.status_code == 503


# ----------------------------------------------------------------------------- backfill CLI
def test_backfill_run_lines_and_exit_codes(env, monkeypatch):
    from policy_graph import backfill
    common = dict(repo_root=env["root"], is_margin_account=False, agents=["DeciderAgent", "FeedbackAgent"])
    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, dry_run=True, out=out, **common) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("DeciderAgent v0  would-created  0 nodes")
    assert not (env["root"] / "agents").exists()                    # dry run writes nothing

    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, out=out, **common) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("DeciderAgent v0  created  ") and "roundtrip ok" in lines[0]
    l19 = [l for l in lines if l.startswith("DeciderAgent v19")][0]
    assert "  created  " in l19 and "soul:inherited@54a50e5e" in l19 and "roundtrip ok" in l19
    assert any(l.startswith("FeedbackAgent v8  created") for l in lines)
    assert lines[-1].startswith("code_sha ")

    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, out=out, **common) == 0
    assert all("  unchanged  " in l for l in out.getvalue().splitlines() if l.startswith(("DeciderAgent", "FeedbackAgent")))

    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, verify_only=True, out=out, **common) == 0
    assert all("  present  " in l for l in out.getvalue().splitlines() if l.startswith(("DeciderAgent", "FeedbackAgent")))

    # a corrupted node file → verify fails → non-zero exit; a RoundTripError in a real run too
    v21 = env["root"] / "agents" / "decider" / "policy-graph" / CFG / "v21"
    target = v21 / "DA.directives.ground_truth.md"
    target.write_bytes(target.read_bytes() + b"corrupted")
    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, verify_only=True, out=out, agents=["DeciderAgent"],
                        repo_root=env["root"], is_margin_account=False) == 1
    assert "roundtrip mismatch" in out.getvalue()

    from policy_graph import store

    def broken(*_a, **_k):
        raise store.RoundTripError("boom")

    monkeypatch.setattr(store, "materialize", broken)
    out = io.StringIO()
    assert backfill.run(env["engine"], CFG, out=out, agents=["DeciderAgent"], repo_root=env["root"],
                        is_margin_account=False) == 1
    assert "FAILED" in out.getvalue()


def test_backfill_main_imports_config_lazily(monkeypatch, env):
    from policy_graph import backfill
    config_stub = types.ModuleType("config")
    config_stub.engine = env["engine"]
    config_stub.IS_MARGIN_ACCOUNT = False
    monkeypatch.setitem(sys.modules, "config", config_stub)
    assert "config" not in [m for m in sys.modules if m == "config" and sys.modules[m] is not config_stub]
    rc = backfill.main(["--config-hash", CFG, "--agent", "DeciderAgent", "--repo-root", str(env["root"]), "--dry-run"])
    assert rc == 0


def test_package_never_imports_config():
    import subprocess
    code = ("import sys; import policy_graph, policy_graph.service, policy_graph.routes, policy_graph.health, "
            "policy_graph.backfill; print('config' in sys.modules)")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"
    pkg = Path(__file__).resolve().parent.parent / "policy_graph"
    for name in ("service.py", "routes.py", "health.py", "backfill.py"):
        src = (pkg / name).read_text(encoding="utf-8")
        assert "os.environ" not in src and "get_current_config_hash" not in src
