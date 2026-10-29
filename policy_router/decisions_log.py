"""Separate audit trail for hosted Decisions comparisons; never active routing.

One row is one attempted shadow cycle, not one question. Failed requests may
have unknown cost; a refusal with valid usage retains its billed input cost.
Only identifiers, hashes, numeric decisions and bounded local diagnostics are
stored. Credentials and full remote/request bodies are never written here.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text

from .decisions import MODEL, PROVIDER

TABLE = "policy_router_comparisons"
DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_router_comparisons (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    run_id TEXT,
    prompt_version INTEGER,
    source_input_id INTEGER,
    source_kind TEXT NOT NULL DEFAULT 'live',
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    policy_hash TEXT,
    question_hash TEXT,
    request_hash TEXT,
    response_id TEXT,
    request_attempted BOOLEAN NOT NULL DEFAULT FALSE,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    cache_write_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DOUBLE PRECISION,
    latency_ms INTEGER,
    note TEXT,
    nodes_json TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    pinned_json TEXT NOT NULL
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
INDEX = "CREATE INDEX IF NOT EXISTS ix_router_comparisons_config_run ON policy_router_comparisons (config_hash, run_id)"


def ensure_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(DDL_POSTGRES if engine.dialect.name == "postgresql" else DDL_SQLITE))
        conn.execute(text(INDEX))


def record_shadow(engine, config_hash: str, prompt_version, run_id: str, result, *, local_result=None,
                  served_ids=(), source_input_id=None, source_kind="live", decided_at=None, economics=None,
                  context_summary=None) -> int:
    """Append one comparison, including unavailable/failed providers, atomically."""
    if source_kind not in ("live", "replay", "observer"):
        raise ValueError("source_kind must be live, replay or observer")
    ensure_schema(engine)
    local = {d.node_id: d for d in ((local_result.selection.decisions if local_result and local_result.selection else []))
             if not d.pinned}
    remote = {d.node_id: d for d in (result.selection.decisions if result.selection else [])}
    served = set(served_ids or ())
    nodes = []
    for ident, node in result.nodes.items():
        ld, rd = local.get(ident), remote.get(ident)
        nodes.append({
            "node_id": ident, "kind": node.kind, "chars": int(node.chars),
            "title": str((getattr(node, "meta", None) or {}).get("title") or ident)[:160],
            "local_p": float(ld.p) if ld else None, "local_choice": ld.choice if ld else None,
            "decisions_p": float(rd.p) if rd else None, "decisions_choice": rd.choice if rd else None,
            "served_in_prompt": ident in served,
        })
    nodes.sort(key=lambda n: (-(n["decisions_p"] if n["decisions_p"] is not None else -1), n["node_id"]))
    comparable = [n for n in nodes if n["local_choice"] is not None and n["decisions_choice"] is not None]
    chars_actual = sum(n["chars"] for n in nodes if n["served_in_prompt"])
    chars_selected = result.selection.chars_selected if result.selection else None
    comparison = {
        "routable": len(nodes), "selected": len(result.selection.included) if result.selection else None,
        "chars_selected": chars_selected, "chars_today": chars_actual,
        "chars_saved": chars_actual - chars_selected if chars_selected is not None else None,
        "expected_recall": result.selection.expected_recall if result.selection else None,
        "comparable": len(comparable),
        "agreements": sum(n["local_choice"] == n["decisions_choice"] for n in comparable),
        "disagreements": sum(n["local_choice"] != n["decisions_choice"] for n in comparable),
        "actual_prompt_changed": False,
        "image_manifest": dict(getattr(result, "image_manifest", None) or {}),
    }
    if economics is not None:
        comparison["economics"] = economics
    if context_summary is not None:
        comparison["context_summary"] = _safe_context_summary(context_summary)
    usage = result.usage or {}
    params = {
        "cfg": config_hash, "run": run_id, "version": prompt_version, "input_id": source_input_id,
        "source": source_kind,
        "at": decided_at or datetime.now(), "status": result.status, "provider": result.provider,
        "model": result.model, "policy": result.policy_hash or None, "question": result.question_hash or None,
        "request": result.request_hash or None, "response": result.response_id,
        "attempted": bool(result.request_attempted),
        "input": usage.get("input_tokens"), "cached": usage.get("cached_input_tokens"),
        "write": usage.get("cache_write_tokens"), "output": usage.get("output_tokens"),
        "cost": result.cost_usd, "latency": result.latency_ms, "note": (result.note or "")[:500],
        "nodes": json.dumps(nodes, allow_nan=False), "comparison": json.dumps(comparison, allow_nan=False),
        "pinned": json.dumps(sorted(set(result.pinned_ids))),
    }
    with engine.begin() as conn:
        return int(conn.execute(text("""
            INSERT INTO policy_router_comparisons (
                config_hash, run_id, prompt_version, source_input_id, source_kind, decided_at, status, provider, model,
                policy_hash, question_hash, request_hash, response_id, request_attempted,
                input_tokens, cached_input_tokens, cache_write_tokens, output_tokens, cost_usd,
                latency_ms, note, nodes_json, comparison_json, pinned_json)
            VALUES (:cfg,:run,:version,:input_id,:source,:at,:status,:provider,:model,:policy,:question,:request,:response,
                :attempted,:input,:cached,:write,:output,:cost,:latency,:note,:nodes,:comparison,:pinned)
            RETURNING id
        """), params).scalar_one())


def _row_public(row, *, nodes: bool = False) -> dict:
    data = dict(row)
    raw_nodes = json.loads(data.pop("nodes_json") or "[]")
    data.update(json.loads(data.pop("comparison_json") or "{}"))
    if "context_summary" in data:
        data["context_summary"] = _safe_context_summary(data["context_summary"])
    data["pinned_ids"] = json.loads(data.pop("pinned_json") or "[]")
    from .economics import unavailable
    data.setdefault("economics", unavailable())
    data["selection"] = {
        "pinned_ids": data["pinned_ids"],
        "selected_ids": [n["node_id"] for n in raw_nodes if n.get("decisions_choice") == "include"],
        "skipped_ids": [n["node_id"] for n in raw_nodes if n.get("decisions_choice") == "exclude"],
        "actual_optional_ids": [n["node_id"] for n in raw_nodes if n.get("served_in_prompt")],
    }
    data["request_attempted"] = bool(data["request_attempted"])
    at = data.get("decided_at")
    data["decided_at"] = at.isoformat() if hasattr(at, "isoformat") else at
    if nodes:
        data["nodes"] = raw_nodes
    return data


def _safe_context_summary(value):
    """The timeline shows identifiers/counts, never account balances or raw prompts."""
    import re
    out = {}
    if not isinstance(value, dict):
        return out
    for key in ("summary_count", "image_count", "actual_decider_image_count", "source_input_id"):
        found = value.get(key)
        if isinstance(found, int) and not isinstance(found, bool) and 0 <= found <= 10_000_000:
            out[key] = found
    for key in ("holdings", "watchlist", "quarantined", "news", "entities", "trend"):
        values = value.get(key) or []
        if isinstance(values, list):
            out[key] = list(dict.fromkeys(str(v).upper() for v in values
                                         if isinstance(v, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,9}", v)))[:60]
    regime = value.get("regime")
    if regime in ("RISK-OFF", "RISK-ON", "MIXED", "UNKNOWN", ""):
        out["regime"] = regime
    if isinstance(value.get("actual_decider_received_images"), bool):
        out["actual_decider_received_images"] = value["actual_decider_received_images"]
    if isinstance(value.get("source_decided_at"), str) and re.fullmatch(r"[0-9T: .+Z-]{1,50}", value["source_decided_at"]):
        out["source_decided_at"] = value["source_decided_at"]
    return out


def cycle_detail(engine, config_hash: str, comparison_id: int):
    """One config-scoped recorded result; this read never scores a guideline."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM policy_router_comparisons WHERE config_hash=:h AND id=:i"),
                               {"h": config_hash, "i": int(comparison_id)}).mappings().first()
    except Exception:
        return None
    if not row:
        return None
    result = _row_public(row, nodes=True)
    if not result.get("context_summary") and result.get("source_input_id") is not None:
        result["context_summary"] = _source_context_summary(engine, config_hash, result["source_input_id"])
    return result


def _source_context_summary(engine, config_hash, source_input_id):
    """Backfill safe display metadata from the exact saved input, not its reply."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text('''SELECT id,run_id,decided_at,context_json FROM decider_inputs
                WHERE config_hash=:h AND id=:i AND call_kind='decide' '''),
                {'h':config_hash,'i':source_input_id}).mappings().first()
            if not row:
                return {}
            count = conn.execute(text('''SELECT COUNT(*) FROM summaries WHERE config_hash=:h
                AND run_id=:r AND timestamp<=:at'''),
                {'h':config_hash,'r':row['run_id'],'at':row['decided_at']}).scalar_one()
        raw = row['context_json'] or '{}'
        if not isinstance(raw, str) or len(raw)>200_000:
            return {}
        context = json.loads(raw)
        if not isinstance(context, dict):
            return {}
        manifest = context.get('image_manifest')
        image_count = 0
        if isinstance(manifest, dict) and manifest.get('config_hash')==config_hash and manifest.get('decision_run_id')==row['run_id']:
            found = manifest.get('image_count')
            if isinstance(found,int) and not isinstance(found,bool) and 0<=found<=12:
                image_count = found
        when = row['decided_at']
        return _safe_context_summary({**context,'source_input_id':int(row['id']),
            'summary_count':int(count),'source_decided_at':when.isoformat() if hasattr(when,'isoformat') else str(when),
            'actual_decider_image_count':image_count,'actual_decider_received_images':image_count>0})
    except Exception:
        return {}


def comparison_panel(engine, config_hash: str, *, last_n: int = 30) -> dict:
    """Bounded UI DTO; safely empty before initialization. Never creates tables."""
    out = {"provider": PROVIDER, "model": MODEL, "runs": [], "last_cycle": None,
           "totals": {"runs": 0, "ok": 0, "fallback": 0, "request_attempts": 0,
                      "cost_usd": None, "known_cost_usd": None, "unknown_cost_calls": 0,
                      "live_runs": 0, "replay_runs": 0, "observer_runs": 0, "input_tokens": 0,
                      "cached_input_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0,
                      "economics_captured_runs": 0, "economics_unavailable_runs": 0,
                      "realized_input_savings_usd": 0.0},
           "note": "Shadow comparison only; no prompt changes or realized savings."}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM policy_router_comparisons WHERE config_hash=:cfg
                ORDER BY id DESC LIMIT :n
            """), {"cfg": config_hash, "n": max(1, min(int(last_n), 200))}).mappings().all()
    except Exception:
        return out
    if not rows:
        return out
    out["runs"] = [_row_public(row) for row in rows]
    out["last_cycle"] = _row_public(rows[0], nodes=True)
    totals = out["totals"]
    totals.update(runs=len(rows), ok=sum(r["status"] == "ok" for r in rows),
                  fallback=sum(r["status"] != "ok" for r in rows),
                  request_attempts=sum(bool(r["request_attempted"]) for r in rows))
    known = [float(r["cost_usd"]) for r in rows if r["cost_usd"] is not None]
    totals["known_cost_usd"] = sum(known) if known else None
    totals["unknown_cost_calls"] = sum(bool(r["request_attempted"]) and r["cost_usd"] is None for r in rows)
    totals["cost_usd"] = totals["known_cost_usd"] if not totals["unknown_cost_calls"] else None
    totals["live_runs"] = sum(r["source_kind"] == "live" for r in rows)
    totals["replay_runs"] = sum(r["source_kind"] == "replay" for r in rows)
    totals["observer_runs"] = sum(r["source_kind"] == "observer" for r in rows)
    for key in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"):
        totals[key] = sum(int(r[key] or 0) for r in rows)
    captured = [r for r in out["runs"] if r["economics"].get("status") == "estimated"]
    totals["economics_captured_runs"] = len(captured)
    totals["economics_unavailable_runs"] = len(rows) - len(captured)
    totals["realized_input_savings_usd"] = 0.0
    totals["economics_note"] = "Bounded recent comparisons. Potential savings require frozen captures; replay and live runs remain identified. Shadow has zero realized input savings."
    return out


__all__ = ["TABLE", "DDL_POSTGRES", "DDL_SQLITE", "ensure_schema", "record_shadow", "comparison_panel", "cycle_detail"]
