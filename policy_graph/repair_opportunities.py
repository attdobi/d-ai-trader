"""Audited operator correction for contradictory regime and macro entry vetoes.

Run ``python repair_opportunities.py --config-hash HASH`` to review
the proposed diff. Nothing is written unless ``--apply`` is supplied. Existing
prompt rows and memory contents are preserved; a database journal records the
old/new prompt references and memory activation states in the same transaction.
No model, broker, or trading-cycle calls are made.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid

from sqlalchemy import text

from policy_safety import OPPORTUNITY_CHARTER, blanket_entry_vetoes, validate_policy_opportunities
from .model import FIELDS


AGENTS = ("DeciderAgent", "FeedbackAgent")
ACTOR = "codex_operator"
ACTION = "operator_policy_repair"
DESCRIPTION = (
    "Operator policy correction: reconcile selective half-size regime/macro entries; "
    "preserve candidate-level stops, earnings exclusions and account rails"
)
_CHARTER_MARKER = "# OPPORTUNITY CHARTER ("
_JOURNAL_DDL = """
CREATE TABLE IF NOT EXISTS opportunity_policy_repairs (
    batch_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
)
"""


class RepairConflict(ValueError):
    """The reviewed policy or memory changed before the repair could commit."""


def _selective_rule(line: str) -> str:
    """Replace an observed unconditional veto without changing other gates."""
    prefix = "- " if line.lstrip().startswith("-") else ""
    number = re.search(r"\b(\d+)\.\s", line)
    prefix += number.group(1) + ". " if number else ""
    if re.search(r"macro\s*[- ]\s*window", line, re.I):
        # Retain the primary EVENT GATE label so citations and factor links keep
        # their existing guideline id across this policy correction.
        label = "EVENT GATE" if "EVENT GATE" in line else "EVENT SIZE"
        return (prefix + label + " — IF EVENT CALENDAR shows MACRO WINDOW: YES THEN allow at most "
                "1 half-size BUY under D≤1.3%, earnings, quarantine, setup and cash gates. "
                "Otherwise next gate. Falsified if 20 compliant entries average below 0%.")
    return (prefix + "REGIME SIZE — IF INDEX REGIME is RISK-OFF THEN evaluate at most 1 half-size BUY "
            "under the current setup, extension, stop, earnings and account gates. Otherwise next gate.")


def _cash_preference(value: str) -> str:
    replacements = (
        ("Cash is valid when no setup clears the filter — and in RISK-OFF it is the default.",
         "Cash is valid when no setup clears the filter; RISK-OFF alone never disqualifies a setup."),
        ("Cash in RISK-OFF is discipline, not failure.",
         "RISK-OFF changes size; candidate-specific gates decide eligibility."),
        ("cash is the correct default, not a failure", "assess selective half-size entries under the current gates"),
        ("cash is the correct default", "assess selective half-size entries under the current gates"),
        ("cash is the default", "assess selective half-size entries"),
        ("cash default", "assess selective entries"),
    )
    for old, new in replacements:
        value = re.sub(re.escape(old), lambda _m, replacement=new: replacement, value, flags=re.I)
    return value


def repair_fields(agent_type: str, fields: dict) -> dict:
    """Pure, idempotent correction of the observed policies; preserve hard rails.

    Numeric history is evidence, not a causal license to remove existing stops.
    Summarizer's existing evidence/allowance reporting is already coherent and
    requires no new version. Unrecognized agents are unchanged.
    """
    out = dict(fields)
    if agent_type not in AGENTS:
        return out
    for field in FIELDS:
        value = fields.get(field)
        if not isinstance(value, str):
            continue
        lines = []
        for line in value.splitlines(keepends=True):
            ending = "\n" if line.endswith("\n") else ""
            body = line.rstrip("\r\n")
            if body.startswith(("Recently EVERY SINGLE DECISION", 'Do NOT place too much weight on "RISK-OFF')):
                continue
            if agent_type == "FeedbackAgent":
                if "[[Risk-off entry pause]] is the next executable regime control:" in body:
                    body = body.replace("[[Risk-off entry pause]] is the next executable regime control:",
                                        "[[Risk-off entry evidence]] remains observational:")
                if "Use the supplied [[INDEX REGIME]] field only: pass new candidates in RISK-OFF." in body:
                    body = ("- Use the supplied [[INDEX REGIME]] field to size selective opportunities under "
                            "the current independent gates. Compare matched candidate/shadow outcomes; "
                            "the six-campaign observation does not authorize a blanket entry pause. "
                            "#decider #falsifiable")
                if "#kill-filter-control" in body:
                    body = ("- **#kill-filter-evidence — Numeric-kill campaigns n=4 averaged -3.96% versus "
                            "20d-only n=21 at -0.37%. This observational comparison does not authorize "
                            "removing current priced-stop requirements.**")
                elif body.startswith("When a ranked loss subgroup and its complete bucket comparison disagree,"):
                    body = ("Report ranked loss subgroups alongside complete bucket comparisons and sample sizes. "
                            "The current comparison is 20d-only n=21 at -0.37% versus numeric n=4 at -3.96%. "
                            "Observational differences do not establish causality or authorize removing existing "
                            "risk controls; use matched candidate or shadow outcomes for a reviewed proposal.")
                body = body.replace(
                    "and do not soften a rule the diagnostics support because the sample is small.",
                    "and state sample uncertainty. Small observational buckets do not authorize removing "
                    "existing risk controls or selective-entry allowances.")
            if blanket_entry_vetoes(body):
                body = _selective_rule(body)
            if agent_type == "DeciderAgent":
                body = _cash_preference(body)
            lines.append(body + ending)
        out[field] = "".join(lines)
    if _CHARTER_MARKER not in (out.get("system_prompt") or ""):
        out["system_prompt"] = (out.get("system_prompt") or "").rstrip() + "\n\n" + OPPORTUNITY_CHARTER
    validate_policy_opportunities(agent_type, {f: out.get(f) for f in FIELDS})
    return out


def _snapshot(conn, config_hash):
    prompts = []
    for agent in AGENTS:
        rows = conn.execute(text("""
            SELECT id, agent_type, version, system_prompt, user_prompt_template,
                   strategy_directives, soul, memory
            FROM prompt_versions
            WHERE config_hash=:cfg AND agent_type=:agent AND is_active=TRUE
            ORDER BY version DESC
        """), {"cfg": config_hash, "agent": agent}).mappings().all()
        if len(rows) != 1:
            raise RepairConflict(f"{agent}: expected exactly one active policy")
        prompts.append(dict(rows[0]))
    memories = [dict(r) for r in conn.execute(text("""
        SELECT id, content, active, updated_at FROM decider_memory
        WHERE config_hash=:cfg AND active=TRUE ORDER BY id
    """), {"cfg": config_hash}).mappings() if blanket_entry_vetoes(r["content"])]
    return {"prompts": prompts, "memories": memories}


def _plan(snapshot):
    changes = []
    for row in snapshot["prompts"]:
        before = {field: row.get(field) for field in FIELDS}
        after = repair_fields(row["agent_type"], before)
        changed = [field for field in FIELDS if before[field] != after[field]]
        if changed:
            changes.append({"row": row, "fields": after, "changed_fields": changed})
    return changes


def _public_plan(snapshot, changes):
    return {
        "applied": False,
        "policy_changes": [{
            "agent_type": c["row"]["agent_type"], "from_version": c["row"]["version"],
            "changed_fields": c["changed_fields"],
            "diff": {field: list(difflib.unified_diff(
                (c["row"].get(field) or "").splitlines(),
                (c["fields"].get(field) or "").splitlines(),
                fromfile=field + ":before", tofile=field + ":after", lineterm=""))
                for field in c["changed_fields"]},
        } for c in changes],
        "deactivate_memory_ids": [r["id"] for r in snapshot["memories"]],
        "memory_content_sha256": {str(r["id"]): hashlib.sha256(r["content"].encode()).hexdigest()
                                  for r in snapshot["memories"]},
    }


def _lock_tables(conn):
    # Short transaction only: no model calls or materialization while held. A
    # table lock also prevents another writer allocating a version concurrently.
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text("LOCK TABLE prompt_versions, decider_memory IN SHARE ROW EXCLUSIVE MODE"))
    elif conn.dialect.name == "sqlite":
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def repair(engine, config_hash, activate, apply=False, *, expected_versions=None):
    """Review or atomically apply an operator repair using the audited switch.

    ``expected_versions`` pins a reviewed dry-run's source versions. Concurrent
    changes between planning and the write transaction abort the entire repair.
    This function supports SQLite for regression tests; the CLI requires Postgres.
    """
    with engine.connect() as conn:
        before = _snapshot(conn, config_hash)
    for row in before["prompts"]:
        expected = (expected_versions or {}).get(row["agent_type"])
        if expected is not None and row["version"] != expected:
            raise RepairConflict(f"{row['agent_type']}: active version changed since review")
    changes = _plan(before)
    result = _public_plan(before, changes)
    if not apply or (not changes and not before["memories"]):
        return result
    if activate is None:
        raise ValueError("An audited activation callback is required")
    batch_id = uuid.uuid4().hex
    journal = {"repair": "opportunities-v1", "policies": [], "memories": []}
    with engine.begin() as conn:
        _lock_tables(conn)
        if _snapshot(conn, config_hash) != before:
            raise RepairConflict("Active policies or veto memories changed during repair planning")
        conn.execute(text(_JOURNAL_DDL))
        for change in changes:
            row = change["row"]
            version = conn.execute(text("""
                SELECT COALESCE(MAX(version), -1)+1 FROM prompt_versions
                WHERE config_hash=:cfg AND agent_type=:agent
            """), {"cfg": config_hash, "agent": row["agent_type"]}).scalar_one()
            params = dict(change["fields"], cfg=config_hash, agent=row["agent_type"],
                          version=version, description=DESCRIPTION, actor=ACTOR)
            new_id = conn.execute(text("""
                INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template,
                    strategy_directives, soul, memory, description, created_by, is_active, config_hash)
                VALUES (:agent, :version, :system_prompt, :user_prompt_template, :strategy_directives,
                    :soul, :memory, :description, :actor, FALSE, :cfg) RETURNING id
            """), params).scalar_one()
            activate(conn, row["agent_type"], config_hash, version, action=ACTION,
                     actor=ACTOR, reason=DESCRIPTION, batch_id=batch_id)
            journal["policies"].append({"agent_type": row["agent_type"], "before_id": row["id"],
                                        "before_version": row["version"], "after_id": new_id,
                                        "after_version": version})
        for row in before["memories"]:
            updated = conn.execute(text("""
                UPDATE decider_memory SET active=FALSE, updated_at=CURRENT_TIMESTAMP
                WHERE config_hash=:cfg AND id=:id AND active=TRUE AND content=:content
            """), dict(row, cfg=config_hash))
            if updated.rowcount != 1:
                raise RepairConflict("A veto memory changed during repair")
            journal["memories"].append({"id": row["id"], "content": row["content"],
                                        "before_active": bool(row["active"]), "after_active": False,
                                        "before_updated_at": str(row["updated_at"])})
        conn.execute(text("""
            INSERT INTO opportunity_policy_repairs (batch_id, config_hash, actor, snapshot_json)
            VALUES (:batch, :cfg, :actor, :snapshot)
        """), {"batch": batch_id, "cfg": config_hash, "actor": ACTOR,
               "snapshot": json.dumps(journal, ensure_ascii=False)})
    result.update(applied=True, batch_id=batch_id, journal=journal)
    return result


def read_backup(engine, config_hash, batch_id):
    """Read original memory state and preserved policy references for review.

    Automatic undo must not bypass the activation validator to revive the old
    blanket vetoes. Use this snapshot to author a reviewed rollback version.
    """
    with engine.connect() as conn:
        value = conn.execute(text("""
            SELECT snapshot_json FROM opportunity_policy_repairs
            WHERE config_hash=:cfg AND batch_id=:batch
        """), {"cfg": config_hash, "batch": batch_id}).scalar_one()
    return json.loads(value)
