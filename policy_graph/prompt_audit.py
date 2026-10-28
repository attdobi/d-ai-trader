"""Versioned operator prompt audit: preview, guarded activation, immutable history.

Configuration is explicit; no model, market-data, broker or environment access.
The caller reviews a plan and supplies the existing audited activation callback.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
import uuid

from sqlalchemy import text

from .model import AGENT_PREFIX, FIELDS
from policy_safety import OPPORTUNITY_CHARTER, validate_policy_opportunities

ACTOR = "codex_operator"
ACTION = "operator_prompt_audit"
SPEC_PATH = Path(__file__).with_name("audited_agent_prompts.json")
DDL = """CREATE TABLE IF NOT EXISTS agent_prompt_audits (
    batch_id TEXT PRIMARY KEY, config_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, actor TEXT NOT NULL,
    source_hash TEXT NOT NULL, journal_json TEXT NOT NULL)"""


class AuditConflict(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def load_spec(path=None):
    return json.loads(Path(path or SPEC_PATH).read_text())


def _placeholders(value):
    # JSON braces are not template fields. This matches the runtime's named placeholders.
    return set(re.findall(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})", value or ""))


def _snapshot(conn, config_hash):
    rows = [dict(r) for r in conn.execute(text("""SELECT id,agent_type,version,system_prompt,
        user_prompt_template,strategy_directives,soul,memory FROM prompt_versions
        WHERE config_hash=:h AND is_active=TRUE ORDER BY agent_type,id"""), {"h": config_hash}).mappings()]
    agents = [r["agent_type"] for r in rows]
    if sorted(agents) != sorted(AGENT_PREFIX):
        raise AuditConflict("Expected exactly one active version of each audited agent")
    memories = [dict(r) for r in conn.execute(text("""SELECT id,content,kind,tags,ticker,source,weight,active,created_at,updated_at
        FROM decider_memory WHERE config_hash=:h ORDER BY id"""), {"h": config_hash}).mappings()]
    return {"prompts": rows, "memories": memories}


def _plan(snapshot, spec):
    changes = []
    configured = spec.get("agents") or {}
    if set(configured) != set(AGENT_PREFIX):
        raise AuditConflict("The audit must explicitly cover all four agents")
    for row in snapshot["prompts"]:
        proposed = configured[row["agent_type"]]
        if int(proposed["from_version"]) != row["version"] or proposed.get("source_row_id") != row["id"]:
            raise AuditConflict(f"{row['agent_type']}: the reviewed source version changed")
        before = {field: row.get(field) or "" for field in FIELDS}
        after = {field: proposed["fields"].get(field) or "" for field in FIELDS}
        if any(not isinstance(v, str) for v in after.values()):
            raise AuditConflict("Every prompt field must be text")
        for field in ("system_prompt", "user_prompt_template"):
            if _placeholders(before[field]) != _placeholders(after[field]):
                raise AuditConflict(f"{row['agent_type']} {field}: template placeholders changed")
        validate_policy_opportunities(row["agent_type"], after)
        changed = [f for f in FIELDS if before[f] != after[f]]
        if changed:
            changes.append({"source": row, "fields": after, "changed_fields": changed,
                            "classification": proposed.get("classification", [])})
    actions = spec.get("memory_actions") or {}
    retire_ids = set(actions.get("retire_ids") or [])
    active = {r["id"]: r for r in snapshot["memories"] if r["active"]}
    if not retire_ids <= active.keys():
        raise AuditConflict("A memory selected for retirement is no longer active")
    return changes, [active[i] for i in sorted(retire_ids)]


def preview(engine, config_hash, *, spec=None):
    spec = spec or load_spec()
    with engine.connect() as conn:
        snapshot = _snapshot(conn, config_hash)
    changes, retired = _plan(snapshot, spec)
    return {"applied": False, "source_hash": _hash(snapshot), "spec_hash": _hash(spec),
            "agents": [{"agent_type": c["source"]["agent_type"], "from_version": c["source"]["version"],
                        "changed_fields": c["changed_fields"], "classification": c["classification"],
                        "characters_before": sum(len(c["source"].get(f) or "") for f in FIELDS),
                        "characters_after": sum(len(c["fields"][f]) for f in FIELDS),
                        "diff": {f: list(difflib.unified_diff((c["source"].get(f) or "").splitlines(),
                                    c["fields"][f].splitlines(), fromfile=f+":before", tofile=f+":after", lineterm=""))
                                 for f in c["changed_fields"]}} for c in changes],
            "retire_memory_ids": [r["id"] for r in retired],
            "new_memory_count": len((spec.get("memory_actions") or {}).get("insert") or [])}


def apply(engine, config_hash, activate, *, expected_source_hash, expected_spec_hash, spec=None):
    """Commit all reviewed agents and memory transitions together; no orders."""
    spec = spec or load_spec()
    if not callable(activate):
        raise ValueError("An audited activation callback is required")
    if _hash(spec) != expected_spec_hash:
        raise AuditConflict("Proposed audit changed after the audit preview")
    batch = uuid.uuid4().hex
    journal = {"audit": "agent-prompts-2026-10-28", "spec_hash": _hash(spec), "policies": [], "memories": []}
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET LOCAL lock_timeout='5s'"))
            conn.execute(text("LOCK TABLE prompt_versions,decider_memory IN SHARE ROW EXCLUSIVE MODE"))
        elif conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        snapshot = _snapshot(conn, config_hash)
        if _hash(snapshot) != expected_source_hash:
            raise AuditConflict("Active policy or memory changed after the audit preview")
        changes, retired = _plan(snapshot, spec)
        conn.execute(text(DDL))
        for change in changes:
            old = change["source"]
            version = int(conn.execute(text("SELECT COALESCE(MAX(version),-1)+1 FROM prompt_versions WHERE config_hash=:h AND agent_type=:a"),
                                       {"h": config_hash, "a": old["agent_type"]}).scalar_one())
            params = {**change["fields"], "h": config_hash, "a": old["agent_type"], "v": version,
                      "actor": ACTOR, "description": spec["agents"][old["agent_type"]].get("description", "Operator prompt readability and evidence audit")}
            new_id = conn.execute(text("""INSERT INTO prompt_versions
                (config_hash,agent_type,version,system_prompt,user_prompt_template,strategy_directives,soul,memory,
                 description,created_by,is_active)
                VALUES (:h,:a,:v,:system_prompt,:user_prompt_template,:strategy_directives,:soul,:memory,
                        :description,:actor,FALSE) RETURNING id"""), params).scalar_one()
            activate(conn, old["agent_type"], config_hash, version, batch_id=batch, action=ACTION,
                     actor=ACTOR, reason=params["description"])
            journal["policies"].append({"agent_type": old["agent_type"], "before_id": old["id"],
                                        "before_version": old["version"], "after_id": int(new_id),
                                        "after_version": version, "classification": change["classification"]})
        for memory in retired:
            conn.execute(text("UPDATE decider_memory SET active=FALSE,updated_at=CURRENT_TIMESTAMP WHERE config_hash=:h AND id=:i"),
                         {"h": config_hash, "i": memory["id"]})
            journal["memories"].append({**memory, "before_active": True, "after_active": False})
        for memory in (spec.get("memory_actions") or {}).get("insert") or []:
            validate_policy_opportunities("DeciderAgent", {"memory": memory["content"]})
            tags = memory.get("tags") or []
            if conn.dialect.name != "postgresql":
                tags = json.dumps(tags)
            new_id = conn.execute(text("""INSERT INTO decider_memory
                (config_hash,kind,tags,ticker,content,source,weight,active)
                VALUES (:h,:kind,:tags,NULL,:content,'operator_audit',:weight,TRUE) RETURNING id"""),
                {"h": config_hash, "kind": memory.get("kind", "lesson"), "tags": tags,
                 "content": memory["content"], "weight": memory.get("weight", 1)}).scalar_one()
            journal["memories"].append({"id": int(new_id), "content": memory["content"], "before_active": False,
                                        "after_active": True, "source": "operator_audit"})
        conn.execute(text("INSERT INTO agent_prompt_audits(batch_id,config_hash,actor,source_hash,journal_json) VALUES (:b,:h,:a,:s,:j)"),
                     {"b": batch, "h": config_hash, "a": ACTOR, "s": expected_source_hash,
                      "j": json.dumps(journal, default=str, ensure_ascii=False)})
    return {"applied": True, "batch_id": batch, **journal}
