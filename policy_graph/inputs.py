"""Decider replay log — the exact inputs and raw reply of every Decider call (`decider_inputs`).

A cycle is replayable when every byte the model read is on record: the assembled system prompt and
the user prompt as sent, the three policy fields as rendered that cycle (soul / directives / memory —
the graph query's output, or the stored text when the flat prompt was used), the assembly Context with
its actual ticker lists (regime, holdings, watchlist, quarantined, news, entities, trend), the ids of
the long-term memory rows injected, the model and reasoning effort, and the model's raw text. These
rows are also the router's training data: which subgraph was served for which context, and what was
cited.

One row per Decider call: `call_kind` 'decide' for the decision call, 'citation_repair' for the
follow-up attribution call. The trader writes the row just before the call (`record_input`) and
completes it after (`record_reply`); both are best effort and never on the critical path.

The table holds holdings and cash: it stays in the local database (no export, no screenshots).
stdlib + `sqlalchemy.text`; never imports config; config_hash is explicit.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import text

CALL_DECIDE = "decide"
CALL_CITATION_REPAIR = "citation_repair"
CONTEXT_KEYS = ("regime", "holdings", "watchlist", "quarantined", "news", "entities", "trend")

DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS decider_inputs (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    run_id TEXT,
    prompt_version INTEGER,
    call_kind TEXT DEFAULT 'decide',
    decided_at TIMESTAMP,
    model TEXT,
    reasoning_effort TEXT,
    system_prompt TEXT,
    user_prompt TEXT,
    policy_soul TEXT,
    policy_directives TEXT,
    policy_memory TEXT,
    context_json TEXT,
    ltm_ids TEXT,
    raw_reply TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
INDEX_RUN_SQL = "CREATE INDEX IF NOT EXISTS ix_decider_inputs_run ON decider_inputs (config_hash, run_id)"
COLUMNS = ("id", "config_hash", "run_id", "prompt_version", "call_kind", "decided_at", "model", "reasoning_effort",
           "system_prompt", "user_prompt", "policy_soul", "policy_directives", "policy_memory", "context_json",
           "ltm_ids", "raw_reply", "created_at")


def ensure_schema(engine) -> None:
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    with engine.begin() as conn:
        conn.execute(text(DDL_POSTGRES if dialect == "postgresql" else DDL_SQLITE))
        try:
            conn.execute(text(INDEX_RUN_SQL))
        except Exception:     # noqa: BLE001 — index creation is best effort
            pass


# ----------------------------------------------------------------------------- payload helpers
def context_payload(source=None, **fields) -> dict:
    """The assembly Context as plain JSON: the regime plus the actual ticker lists, in the order the
    trader built them (blanks dropped). `source` is a policy_graph.assembly.Context or a dict;
    keyword fields override it."""
    out: dict = {}
    for key in CONTEXT_KEYS:
        if key in fields:
            value = fields[key]
        elif isinstance(source, dict):
            value = source.get(key)
        else:
            value = getattr(source, key, None)
        if key == "regime":
            out[key] = str(value or "")
        else:
            out[key] = [str(t) for t in (value or []) if t]
    return out


def ltm_row_ids(rows: Optional[Iterable]) -> list:
    """Integer row ids of the injected decider_memory rows (dicts with `id`, bare ids, or 'DA.ltm.<id>')."""
    out = []
    for r in rows or []:
        rid = r.get("id") if isinstance(r, dict) else r
        if isinstance(rid, str) and rid.startswith("DA.ltm."):
            rid = rid[len("DA.ltm."):]
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        if rid not in out:
            out.append(rid)
    return out


def raw_text(reply) -> Optional[str]:
    """The model's reply as text: strings verbatim, parsed objects as JSON (None stays None)."""
    if reply is None:
        return None
    if isinstance(reply, str):
        return reply
    try:
        return json.dumps(reply, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(reply)


# ----------------------------------------------------------------------------- writes
def record_input(engine, config_hash: str, *, run_id: Optional[str], prompt_version=None,
                 system_prompt: Optional[str] = None, user_prompt: Optional[str] = None,
                 policy: Optional[dict] = None, context=None, ltm_ids=None, model: Optional[str] = None,
                 reasoning_effort: Optional[str] = None, call_kind: str = CALL_DECIDE, decided_at=None) -> Optional[int]:
    """Insert one row for a Decider call about to be made; returns its id. `policy` is
    {"soul", "directives", "memory"} as rendered; `context` a Context / dict (see context_payload)."""
    policy = policy or {}
    params = {
        "h": config_hash, "r": run_id,
        "v": (int(prompt_version) if prompt_version is not None else None),
        "k": call_kind or CALL_DECIDE, "t": decided_at or datetime.now(),
        "m": model, "e": reasoning_effort, "sp": system_prompt, "up": user_prompt,
        "ps": policy.get("soul"), "pd": policy.get("directives"), "pm": policy.get("memory"),
        "ctx": (json.dumps(context_payload(context), ensure_ascii=False, sort_keys=True) if context is not None else None),
        "ltm": json.dumps(ltm_row_ids(ltm_ids)) if ltm_ids is not None else None,
    }
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO decider_inputs (config_hash, run_id, prompt_version, call_kind, decided_at, model, reasoning_effort,
                system_prompt, user_prompt, policy_soul, policy_directives, policy_memory, context_json, ltm_ids)
            VALUES (:h, :r, :v, :k, :t, :m, :e, :sp, :up, :ps, :pd, :pm, :ctx, :ltm)
            RETURNING id
        """), params).fetchone()
    return int(row[0]) if row and row[0] is not None else None


_UNSET = object()


def record_reply(engine, input_id, reply, *, model=_UNSET, reasoning_effort=_UNSET, system_prompt=_UNSET,
                 user_prompt=_UNSET) -> bool:
    """Complete a row with the model's raw text. `model` / `reasoning_effort` / the prompts replace the
    pre-call values only when passed — None included, e.g. no reasoning effort on a fallback model (the
    call may have fallen back to another model, and the client may have appended its own reasoning line
    to the system prompt). False when there is no row."""
    if input_id is None:
        return False
    sets, params = ["raw_reply = :raw"], {"id": int(input_id), "raw": raw_text(reply)}
    for col, key, value in (("model", "m", model), ("reasoning_effort", "e", reasoning_effort),
                            ("system_prompt", "sp", system_prompt), ("user_prompt", "up", user_prompt)):
        if value is not _UNSET:
            sets.append(f"{col} = :{key}")
            params[key] = value
    with engine.begin() as conn:
        res = conn.execute(text(f"UPDATE decider_inputs SET {', '.join(sets)} WHERE id = :id"), params)
    return bool(getattr(res, "rowcount", 0))


# ----------------------------------------------------------------------------- reads (replay)
def _decode(row: dict) -> dict:
    out = dict(row)
    for col, empty in (("context_json", {}), ("ltm_ids", [])):
        raw = out.get(col)
        try:
            out[col] = json.loads(raw) if raw else empty
        except (TypeError, ValueError):
            out[col] = empty
    return out


def load_inputs(engine, config_hash: str, run_id: str, *, call_kind: Optional[str] = None) -> list:
    """Every logged call of one run, oldest first, with context_json / ltm_ids decoded."""
    sql = f"SELECT {', '.join(COLUMNS)} FROM decider_inputs WHERE config_hash = :h AND run_id = :r"
    params = {"h": config_hash, "r": run_id}
    if call_kind:
        sql += " AND call_kind = :k"
        params["k"] = call_kind
    with engine.connect() as conn:
        rows = conn.execute(text(sql + " ORDER BY id"), params).fetchall()
    return [_decode(dict(r._mapping)) for r in rows]


def latest_input(engine, config_hash: str, *, call_kind: str = CALL_DECIDE) -> Optional[dict]:
    """The most recent logged call of one kind, decoded; None when nothing is logged."""
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT {', '.join(COLUMNS)} FROM decider_inputs
            WHERE config_hash = :h AND call_kind = :k ORDER BY id DESC LIMIT 1
        """), {"h": config_hash, "k": call_kind}).fetchone()
    return _decode(dict(row._mapping)) if row is not None else None


__all__ = ["CALL_DECIDE", "CALL_CITATION_REPAIR", "CONTEXT_KEYS", "COLUMNS", "DDL_POSTGRES", "DDL_SQLITE",
           "INDEX_RUN_SQL", "ensure_schema", "context_payload", "ltm_row_ids", "raw_text", "record_input",
           "record_reply", "load_inputs", "latest_input"]
