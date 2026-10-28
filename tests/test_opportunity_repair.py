"""Operator correction is reviewable, atomic, scoped, and preserves hard gates."""
from __future__ import annotations


import pytest
from sqlalchemy import create_engine, inspect, text

from policy_graph import repair_opportunities as repair_module
from policy_graph.model import FIELDS
from policy_graph.repair_opportunities import (
    ACTOR, ACTION, RepairConflict, read_backup, repair, repair_fields,
)
from policy_safety import OPPORTUNITY_CHARTER, blanket_entry_vetoes, validate_policy_opportunities


CFG = "local-policy-test"
VETO = "3. EVENT — IF EVENT CALENDAR for a new BUY shows MACRO WINDOW flag 1 THEN pass. Otherwise next gate."
RISK_VETO = "1. REGIME — If INDEX REGIME=RISK-OFF, PASS every new buy; otherwise fall through."
HARD_KILL = "IF numeric D is missing or D >1.3% THEN PASS."
EARNINGS = "IF earnings are within 5 sessions THEN pass."


def _fields(agent):
    common = {field: "" for field in FIELDS}
    if agent == "DeciderAgent":
        common.update(
            system_prompt="RISK-OFF: cash is the correct default; at most 1 new BUY at half size.\n"
                          + HARD_KILL + "\n"
                          + 'Recently EVERY SINGLE DECISION IS "HOLD CASH" turn off the risk gate!\n',
            user_prompt_template="RISK-OFF = cash default, ≤1 half-size BUY, oversold reversal or ≤3% above the 20d MA.\n"
                                 "Respect settled cash, ≤5 holdings, quarantine and correlation caps.\n",
            strategy_directives="9. EVENT GATE — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN pass. Otherwise next gate.\n"
                                + EARNINGS + "\n## Latest Feedback Reminder\n- " + VETO,
            soul="Read regime; in RISK-OFF, cash is the correct default, not a failure.\n"
                 'Do NOT place too much weight on "RISK-OFF ..." because this is preventing great trading opportunities.\n',
            memory="## 2026-10-15\n- " + VETO + "\nKeep numeric kills binding, do not widen stops.\n",
        )
    else:
        common.update(
            system_prompt="Do not overfit one anecdote, and do not soften a rule the diagnostics support because the sample is small.",
            soul="- **#risk-off-entry-pause — 1. RISK-OFF PAUSE — IF INDEX REGIME is RISK-OFF THEN pass. Otherwise next gate.**\n"
                 "- **#kill-filter-control — Do not issue or retain a D:% requirement while numeric-kill campaigns are n=4 at -3.96% versus 20d-only n=21 at -0.37%.**\n"
                 "When a ranked loss subgroup and its complete bucket comparison disagree, retain retirement of numeric D.",
            memory="## 2026-10-28\n"
                   "- [[Risk-off entry pause]] is the next executable regime control: all 6 RISK-OFF campaigns averaged -0.75% and lost $24.03.\n"
                   "- Use the supplied [[INDEX REGIME]] field only: pass new candidates in RISK-OFF. Falsify only if 20 RISK-OFF entries average 0.00% or better. #decider #falsifiable\n",
        )
    return common


def test_pure_transform_resolves_conflicts_preserves_risk_controls_and_is_idempotent():
    original = _fields("DeciderAgent")
    before = dict(original)
    corrected = repair_fields("DeciderAgent", original)
    assert original == before
    assert not blanket_entry_vetoes(corrected)
    assert HARD_KILL in corrected["system_prompt"]
    assert EARNINGS in corrected["strategy_directives"]
    assert "Respect settled cash, ≤5 holdings, quarantine and correlation caps." in corrected["user_prompt_template"]
    assert "oversold reversal or ≤3% above the 20d MA" in corrected["user_prompt_template"]
    assert "D≤1.3%" in corrected["strategy_directives"]
    assert "at most 1 half-size BUY" in corrected["memory"]
    assert "turn off the risk gate" not in corrected["system_prompt"]
    assert "cash default" not in corrected["user_prompt_template"]
    assert OPPORTUNITY_CHARTER in corrected["system_prompt"]
    assert repair_fields("DeciderAgent", corrected) == corrected


def test_feedback_retains_observations_without_unilateral_ban_or_stop_retirement():
    corrected = repair_fields("FeedbackAgent", _fields("FeedbackAgent"))
    assert "all 6 RISK-OFF campaigns averaged -0.75% and lost $24.03" in corrected["memory"]
    assert "pass new candidates in RISK-OFF" not in corrected["memory"]
    assert "not authorize removing" in corrected["soul"]
    assert "n=4" in corrected["soul"] and "-3.96%" in corrected["soul"]
    assert "Small observational buckets" in corrected["system_prompt"]
    validate_policy_opportunities("FeedbackAgent", corrected)
    assert repair_fields("FeedbackAgent", corrected) == corrected


def test_coherent_summarizer_and_unrelated_fields_are_unchanged():
    fields = {"system_prompt": "Surface the event, date, allowance and missing evidence.", "other": 7}
    assert repair_fields("SummarizerAgent", fields) == fields
    assert repair_fields("CompanyExtractionAgent", fields) == fields


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, agent_type TEXT, config_hash TEXT,
                version INTEGER, system_prompt TEXT, user_prompt_template TEXT,
                strategy_directives TEXT, soul TEXT, memory TEXT, description TEXT,
                created_by TEXT, is_active BOOLEAN DEFAULT FALSE)
        """))
        conn.execute(text("""
            CREATE TABLE decider_memory (
                id INTEGER PRIMARY KEY, config_hash TEXT, content TEXT,
                active BOOLEAN, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """))
        conn.execute(text("""
            CREATE TABLE prompt_activation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT, config_hash TEXT,
                agent_type TEXT, from_version INTEGER, to_version INTEGER,
                action TEXT, actor TEXT, reason TEXT)
        """))
        for agent, version in (("DeciderAgent", 58), ("FeedbackAgent", 14)):
            conn.execute(text("""
                INSERT INTO prompt_versions (agent_type, config_hash, version, system_prompt,
                    user_prompt_template, strategy_directives, soul, memory, is_active)
                VALUES (:agent, :cfg, :version, :system_prompt, :user_prompt_template,
                    :strategy_directives, :soul, :memory, TRUE)
            """), dict(_fields(agent), agent=agent, cfg=CFG, version=version))
        for ident, cfg, content, active in (
            (924, CFG, RISK_VETO, True), (939, CFG, VETO, True),
            (24, CFG, "Use half size in RISK-OFF.", True),
            (42, CFG, VETO, False), (33, "other-config", RISK_VETO, True),
        ):
            conn.execute(text("INSERT INTO decider_memory (id,config_hash,content,active) VALUES (:i,:c,:t,:a)"),
                         {"i": ident, "c": cfg, "t": content, "a": active})
    yield engine
    engine.dispose()


def _activate(conn, agent_type, config_hash, version, **audit):
    fields = conn.execute(text("SELECT system_prompt,user_prompt_template,strategy_directives,soul,memory "
                               "FROM prompt_versions WHERE agent_type=:a AND config_hash=:c AND version=:v"),
                          {"a": agent_type, "c": config_hash, "v": version}).mappings().one()
    validate_policy_opportunities(agent_type, fields)
    old = conn.execute(text("SELECT version FROM prompt_versions WHERE agent_type=:a AND config_hash=:c AND is_active=TRUE"),
                       {"a": agent_type, "c": config_hash}).scalar_one()
    conn.execute(text("UPDATE prompt_versions SET is_active=FALSE WHERE agent_type=:a AND config_hash=:c"),
                 {"a": agent_type, "c": config_hash})
    conn.execute(text("UPDATE prompt_versions SET is_active=TRUE WHERE agent_type=:a AND config_hash=:c AND version=:v"),
                 {"a": agent_type, "c": config_hash, "v": version})
    conn.execute(text("""
        INSERT INTO prompt_activation_events (batch_id,config_hash,agent_type,from_version,to_version,action,actor,reason)
        VALUES (:batch_id,:cfg,:agent,:old,:new,:action,:actor,:reason)
    """), dict(audit, cfg=config_hash, agent=agent_type, old=old, new=version))


def _state(engine):
    with engine.connect() as conn:
        return {table: [dict(row) for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
                for table in ("prompt_versions", "decider_memory", "prompt_activation_events")}


def test_default_is_a_real_read_only_dry_run(db):
    before = _state(db)
    result = repair(db, CFG, _activate)
    assert result["applied"] is False
    assert result["deactivate_memory_ids"] == [924, 939]
    assert len(result["policy_changes"]) == 2
    assert result["policy_changes"][0]["diff"]["system_prompt"]
    assert _state(db) == before
    assert "opportunity_policy_repairs" not in inspect(db).get_table_names()


def test_apply_is_atomic_audited_content_based_and_idempotent(db):
    before = _state(db)
    result = repair(db, CFG, _activate, apply=True,
                    expected_versions={"DeciderAgent": 58, "FeedbackAgent": 14})
    after = _state(db)
    assert result["applied"] is True
    assert len(after["prompt_versions"]) == 4
    assert {(r["agent_type"], r["version"]) for r in after["prompt_versions"] if r["is_active"]} == {
        ("DeciderAgent", 59), ("FeedbackAgent", 15)}
    for old, new in zip(before["prompt_versions"], after["prompt_versions"]):
        assert {k: v for k, v in new.items() if k != "is_active"} == {k: v for k, v in old.items() if k != "is_active"}
    assert {r["id"]: bool(r["active"]) for r in after["decider_memory"]} == {
        24: True, 33: True, 42: False, 924: False, 939: False}
    assert [r["content"] for r in before["decider_memory"]] == [r["content"] for r in after["decider_memory"]]
    events = after["prompt_activation_events"]
    assert len(events) == 2
    assert {e["batch_id"] for e in events} == {result["batch_id"]}
    assert all(e["actor"] == ACTOR and e["action"] == ACTION for e in events)
    backup = read_backup(db, CFG, result["batch_id"])
    assert {r["id"] for r in backup["memories"]} == {924, 939}
    assert all(r["before_active"] and not r["after_active"] for r in backup["memories"])
    second = repair(db, CFG, _activate, apply=True)
    assert not second["applied"] and not second["policy_changes"] and not second["deactivate_memory_ids"]
    assert _state(db) == after


def test_failed_activation_rolls_back_all_policy_memory_and_audit_writes(db):
    before = _state(db)
    def fail_second(conn, agent, cfg, version, **audit):
        if agent == "FeedbackAgent":
            raise RuntimeError("test failure")
        _activate(conn, agent, cfg, version, **audit)
    with pytest.raises(RuntimeError, match="test failure"):
        repair(db, CFG, fail_second, apply=True)
    assert _state(db) == before


def test_expected_review_version_prevents_stale_apply(db):
    before = _state(db)
    with pytest.raises(RepairConflict, match="changed since review"):
        repair(db, CFG, _activate, apply=True, expected_versions={"DeciderAgent": 57})
    assert _state(db) == before


def test_change_between_plan_and_lock_is_rejected(db, monkeypatch):
    before = _state(db)
    lock = repair_module._lock_tables
    def concurrent_change(conn):
        # This represents a completed writer between the initial read and lock.
        conn.execute(text("UPDATE prompt_versions SET memory='new human edit' WHERE agent_type='DeciderAgent'"))
        # SQLite has already begun its transaction for the test mutation.
        if conn.dialect.name != "sqlite":
            lock(conn)
    monkeypatch.setattr(repair_module, "_lock_tables", concurrent_change)
    with pytest.raises(RepairConflict, match="changed during repair planning"):
        repair(db, CFG, _activate, apply=True)
    assert _state(db) == before


@pytest.mark.parametrize("price,ma,earnings_sessions,eligible", [
    (55.86, 55.75, None, True),  # PYPL, saved input144
    (81.24, 80.50, None, True),  # GM, saved input144
    (20.43, 19.87, 6, False),    # DKNG: D>1.3%
    (20.69, 21.36, 1, False),    # PINS: invalid above-entry stop and earnings
])
def test_saved_candidate_geometry_does_not_require_relaxing_stop_or_earnings_gates(price, ma, earnings_sessions, eligible):
    """Arithmetic eligibility only, not a model replay or predicted trade result."""
    stop = max(ma, price * 0.97)
    distance = (price - stop) / price * 100
    clears = (0 < distance <= 1.3 and (earnings_sessions is None or earnings_sessions > 5))
    assert clears is eligible
    # Unknown earnings are left unknown; the fixture does not assert safety.


def test_cli_apply_is_explicit_and_rejects_fallback_database(monkeypatch, capsys):
    import sys
    from types import SimpleNamespace
    import repair_opportunities as cli
    fake = SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setitem(sys.modules, "config", fake)
    monkeypatch.setitem(sys.modules, "prompt_manager", SimpleNamespace(
        refresh_latest_policy_graph=lambda *a, **kw: None,
        set_active_prompt_version=_activate))
    with pytest.raises(SystemExit, match="Postgres is required"):
        cli.main(["--config-hash", CFG])
    assert capsys.readouterr().out == ""
