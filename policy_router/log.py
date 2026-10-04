"""Router logs: one row per routable node per cycle, one summary row per cycle.

policy_router_decisions   run_id, config_hash, prompt_version, decided_at, mode, node_id, kind, p, p_base, choice,
                          served_in_prompt, backend (embed | embed+llm | fallback), model_version, chars
policy_router_runs        the cycle summary: requested / effective mode, certified, counts, routable chars, chars
                          the router selects vs what today's prompt served, expected recall, latency, note

`served_in_prompt` is what the Decider actually read: in shadow mode today's selection, in active mode the
router's. Joined with policy_graph_hits (cited = true) on (config_hash, run_id, node_id) this gives the
shadow recall of explicit citations (`shadow_recall`). DDL is portable (Postgres / SQLite); init_database.py
creates both tables from these constants.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import text

DDL_DECISIONS_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_router_decisions (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    config_hash VARCHAR(50) NOT NULL,
    prompt_version INTEGER,
    decided_at TIMESTAMP,
    mode TEXT,
    node_id TEXT NOT NULL,
    kind TEXT,
    p DOUBLE PRECISION,
    p_base DOUBLE PRECISION,
    choice TEXT,
    served_in_prompt BOOLEAN,
    backend TEXT,
    model_version TEXT,
    chars INTEGER
)
"""
DDL_RUNS_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_router_runs (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    config_hash VARCHAR(50) NOT NULL,
    prompt_version INTEGER,
    decided_at TIMESTAMP,
    mode TEXT,
    effective_mode TEXT,
    backend TEXT,
    model_version TEXT,
    certified BOOLEAN,
    routable INTEGER,
    selected INTEGER,
    chars_routable INTEGER,
    chars_selected INTEGER,
    chars_today INTEGER,
    chars_saved INTEGER,
    expected_recall DOUBLE PRECISION,
    latency_ms INTEGER,
    note TEXT
)
"""
DDL_DECISIONS_SQLITE = DDL_DECISIONS_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
DDL_RUNS_SQLITE = DDL_RUNS_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_policy_router_decisions_run ON policy_router_decisions (config_hash, run_id)",
    "CREATE INDEX IF NOT EXISTS ix_policy_router_decisions_node ON policy_router_decisions (config_hash, node_id, decided_at)",
    "CREATE INDEX IF NOT EXISTS ix_policy_router_runs_run ON policy_router_runs (config_hash, run_id)",
)


def ensure_schema(engine) -> None:
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    pg = dialect == "postgresql"
    with engine.begin() as conn:
        conn.execute(text(DDL_DECISIONS_POSTGRES if pg else DDL_DECISIONS_SQLITE))
        conn.execute(text(DDL_RUNS_POSTGRES if pg else DDL_RUNS_SQLITE))
        for ddl in INDEXES:
            try:
                conn.execute(text(ddl))
            except Exception:     # noqa: BLE001 — index creation is best effort
                pass


def record_routing(engine, config_hash: str, prompt_version, run_id: str, result, *, served_ids: Iterable = (),
                   decided_at: Optional[datetime] = None) -> int:
    """Insert the cycle's node rows and its summary row. `served_ids` = routable ids the prompt carried.
    Returns the number of node rows written."""
    ensure_schema(engine)
    at = decided_at or datetime.now()
    served = set(served_ids or ())
    sel = getattr(result, "selection", None)
    decisions = [d for d in (sel.decisions if sel is not None else []) if not d.pinned]
    nodes = getattr(result, "nodes", {}) or {}
    rows = [{"r": run_id, "h": config_hash, "v": prompt_version, "t": at, "m": result.effective_mode,
             "n": d.node_id, "k": d.kind, "p": float(d.p), "pb": (float(d.p_base) if d.p_base is not None else None),
             "c": d.choice, "s": d.node_id in served, "b": result.backend, "mv": result.model_version or None,
             "ch": int(d.chars)} for d in decisions]
    chars_today = getattr(result, "chars_today", None)          # what today's selection serves of the routable nodes
    if chars_today is None:
        chars_today = sum(int(n.chars) for nid, n in nodes.items() if nid in served)
    chars_sel = sel.chars_selected if sel is not None else None
    with engine.begin() as conn:
        if rows:
            conn.execute(text("""
                INSERT INTO policy_router_decisions (run_id, config_hash, prompt_version, decided_at, mode, node_id, kind,
                    p, p_base, choice, served_in_prompt, backend, model_version, chars)
                VALUES (:r, :h, :v, :t, :m, :n, :k, :p, :pb, :c, :s, :b, :mv, :ch)
            """), rows)
        conn.execute(text("""
            INSERT INTO policy_router_runs (run_id, config_hash, prompt_version, decided_at, mode, effective_mode, backend,
                model_version, certified, routable, selected, chars_routable, chars_selected, chars_today, chars_saved,
                expected_recall, latency_ms, note)
            VALUES (:r, :h, :v, :t, :m, :em, :b, :mv, :cert, :nr, :ns, :cr, :cs, :ct, :saved, :er, :lat, :note)
        """), {"r": run_id, "h": config_hash, "v": prompt_version, "t": at, "m": result.requested_mode,
               "em": result.effective_mode, "b": result.backend, "mv": result.model_version or None,
               "cert": bool(result.certified), "nr": len(decisions),
               "ns": sum(1 for d in decisions if d.choice == "include") if sel is not None else None,
               "cr": sel.chars_routable if sel is not None else None, "cs": chars_sel, "ct": chars_today,
               "saved": (chars_today - chars_sel) if chars_sel is not None else None,
               "er": float(sel.expected_recall) if sel is not None else None, "lat": int(result.latency_ms or 0),
               "note": (result.note or None)})
    return len(rows)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def recent_runs(engine, config_hash: str, *, limit: int = 30) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT run_id, decided_at, prompt_version, mode, effective_mode, backend, model_version, certified, routable,
                   selected, chars_routable, chars_selected, chars_today, chars_saved, expected_recall, latency_ms, note
            FROM policy_router_runs WHERE config_hash = :h ORDER BY id DESC LIMIT :n
        """), {"h": config_hash, "n": int(limit)}).fetchall()
    out = []
    for r in rows:
        m = dict(r._mapping)
        m["decided_at"] = _iso(m.get("decided_at"))
        m["certified"] = bool(m.get("certified")) if m.get("certified") is not None else None
        out.append(m)
    return out


def run_decisions(engine, config_hash: str, run_id: str) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT node_id, kind, p, p_base, choice, served_in_prompt, chars FROM policy_router_decisions
            WHERE config_hash = :h AND run_id = :r ORDER BY p DESC, node_id
        """), {"h": config_hash, "r": run_id}).fetchall()
    return [{"node_id": r[0], "kind": r[1], "p": float(r[2]) if r[2] is not None else None,
             "p_base": float(r[3]) if r[3] is not None else None, "choice": r[4],
             "served_in_prompt": bool(r[5]) if r[5] is not None else None, "chars": int(r[6] or 0)} for r in rows]


def shadow_recall(engine, config_hash: str, *, last_n: int = 30) -> dict:
    """Over the last N routed cycles: routable nodes the Decider cited (policy_graph_hits.cited) and how many of
    them the router included / today's prompt served. Recall is None until a routable node is ever cited."""
    runs = [r for r in recent_runs(engine, config_hash, limit=last_n) if r.get("effective_mode") != "fallback"]
    ids = [r["run_id"] for r in runs if r.get("run_id")]
    out = {"runs": len(ids), "cited": 0, "router_kept": 0, "today_kept": 0, "recall": None, "today_recall": None,
           "avg_chars_selected": None, "avg_chars_today": None}
    if not ids:
        return out
    from sqlalchemy import bindparam
    stmt = text("""
        SELECT d.run_id, d.node_id, d.choice, d.served_in_prompt FROM policy_router_decisions d
        WHERE d.config_hash = :h AND d.run_id IN :ids AND EXISTS (
            SELECT 1 FROM policy_graph_hits x WHERE x.config_hash = d.config_hash AND x.run_id = d.run_id
              AND x.node_id = d.node_id AND x.cited = :cited)
    """).bindparams(bindparam("ids", expanding=True))
    try:
        with engine.connect() as conn:
            rows = conn.execute(stmt, {"h": config_hash, "ids": ids, "cited": True}).fetchall()
    except Exception:     # noqa: BLE001 — the hit log may not exist (fresh install)
        rows = []
    seen = set()
    for run_id, node_id, choice, served in rows:
        if (run_id, node_id) in seen:
            continue
        seen.add((run_id, node_id))
        out["cited"] += 1
        out["router_kept"] += int(choice == "include")
        out["today_kept"] += int(bool(served))
    if out["cited"]:
        out["recall"] = out["router_kept"] / out["cited"]
        out["today_recall"] = out["today_kept"] / out["cited"]
    sel = [r["chars_selected"] for r in runs if r.get("chars_selected") is not None]
    tod = [r["chars_today"] for r in runs if r.get("chars_today") is not None]
    out["avg_chars_selected"] = (sum(sel) / len(sel)) if sel else None
    out["avg_chars_today"] = (sum(tod) / len(tod)) if tod else None
    return out


__all__ = ["DDL_DECISIONS_POSTGRES", "DDL_RUNS_POSTGRES", "INDEXES", "ensure_schema", "record_routing", "recent_runs",
           "run_decisions", "shadow_recall"]
