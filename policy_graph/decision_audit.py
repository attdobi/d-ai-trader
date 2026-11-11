"""Read saved Decider evidence across the model, validation, and execution stages."""
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
import re
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, inspect, text

from .citations import is_rejection, normalize_ids, parse_cites, strip_cites


PACIFIC = ZoneInfo("America/Los_Angeles")
ORDER_ACTIONS = {"buy", "sell"}
NO_ORDER = {"rejected", "canceled", "cancelled", "expired", "failed", "error",
            "not_executed", "capped", "not_filled", "skipped", "market_closed"}


def _decode(value):
    if not isinstance(value, str):
        return value
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value.strip(), re.I | re.S)
    try:
        return json.loads(fenced[1] if fenced else value)
    except ValueError:
        return None


def _objects(items):
    return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []


def _reason(row):
    reason = row.get("reason") or row.get("why") or ""
    supplied = row.get("cited")
    ids = normalize_ids(supplied) if isinstance(supplied, (str, list)) else []
    return {"reason": strip_cites(reason)[:1800], "cited": list(dict.fromkeys(parse_cites(reason) + ids))}


def _decision(row):
    return {"ticker": str(row.get("ticker") or row.get("symbol") or "").strip().upper(),
            "action": str(row.get("action") or "").strip().lower(), **_reason(row)}


def _execution(row):
    status = str(row.get("execution_status") or "").strip().lower()
    if status == "filled" or row.get("executed_amount") is not None:
        return "filled"
    if status in NO_ORDER:
        return "not filled"
    return "unconfirmed"


def _screened(row):
    features = _decode(row["features_json"])
    if not isinstance(features, dict):
        features = {}
    price, ma = features.get("price"), features.get("sma20")
    ma_distance = None
    if all(isinstance(value, (float, int)) and math.isfinite(value) and value > 0 for value in (price, ma)):
        ma_distance = round(100 * (price - ma) / price, 2)
    return {"ticker": row["ticker"], "ma_distance_pct": ma_distance}


def _cycle(row, capture, event, candidates, served, router=None):
    saved = _objects(_decode(row["data"]))
    raw = _decode(capture.get("raw_reply"))
    raw_actions = raw.get("decisions") if isinstance(raw, dict) else raw
    if isinstance(raw, dict) and raw.get("action"):
        raw_actions = [raw]
    # An empty decoded list is evidence of zero proposals. An absent or
    # malformed capture cannot establish what the model proposed.
    proposed = None
    if isinstance(raw_actions, list) and all(isinstance(item, dict) and item.get("action") for item in raw_actions):
        proposed = [_decision(item) for item in raw_actions]
    decisions = []
    considered = []
    cash_reason = ""
    cash_cited = []
    for item in saved:
        if item.get("kind") == "considered_audit":
            considered.extend(_objects(item.get("considered")))
            continue
        decision = _decision(item)
        if decision["ticker"] == "CASH":
            cash_reason = decision["reason"]
            cash_cited = decision["cited"]
            continue
        if decision["action"] in ORDER_ACTIONS:
            decision.update(execution=_execution(item), status=item.get("execution_status"),
                            execution_error=str(item.get("execution_error") or "")[:700])
        if decision["action"] in {"buy", "sell", "hold"}:
            decisions.append(decision)
    if isinstance(raw, dict):
        cash_reason = cash_reason or str(raw.get("cash_reason") or "")[:1800]
    proposals = [p for p in proposed or [] if p["action"] in ORDER_ACTIONS]
    stored_keys = {(d["ticker"], d["action"]) for d in decisions}
    assessments = [{"ticker": _decision(item)["ticker"], "verdict": str(item.get("verdict") or ""),
                    "signals": str(item.get("signals") or "")[:900],
                    "passed": is_rejection(item), **_reason(item)} for item in considered]
    buy_rows = [d for d in decisions if d["action"] == "buy"]
    at = row["timestamp"]
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=PACIFIC)  # trade_decisions stores naive Pacific time
    context = _decode(capture.get("context_json"))
    if not isinstance(context, dict):
        context = {}
    held = context.get("holdings")
    if isinstance(held, list):
        held = {str(ticker).upper() for ticker in held}
    screened = [{**c, "held": c["ticker"] in held if isinstance(held, set) else None} for c in candidates]
    cited = set(cash_cited).union(node for item in decisions + assessments for node in item["cited"])
    return {"id": row["id"], "run_id": row["run_id"], "at": at.isoformat() if at else None,
            "version": capture.get("prompt_version"), "model": capture.get("model"),
            "reasoning": capture.get("reasoning_effort"), "regime": context.get("regime") or event.get("regime"),
            "risk_score": event.get("risk_score"), "macro_window": event.get("macro_window"),
            "session_recovery_supplied": capture.get("session_recovery_supplied"),
            "router": router,
            "cash_reason": cash_reason, "cash_cited": cash_cited, "decisions": decisions, "considered": assessments,
            "screened": screened, "served_citations": sorted(cited & served),
            "served_logged": bool(served),
            "model_buys": None if proposed is None else sum(p["action"] == "buy" for p in proposals),
            "stored_buys": len(buy_rows), "filled_buys": sum(d["execution"] == "filled" for d in buy_rows),
            "missing_decisions": [p for p in proposals if (p["ticker"], p["action"]) not in stored_keys]}


def audit_cycles(engine, config_hash, *, limit=20):
    """Bounded read with optional capture tables for older databases."""
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        if "trade_decisions" not in tables:
            return {"cycles": []}
        rows = conn.execute(text("""
            SELECT id, run_id, timestamp, data FROM trade_decisions
            WHERE config_hash = :h ORDER BY id DESC LIMIT :limit
        """), {"h": config_hash, "limit": limit}).mappings().all()
        runs = list({row["run_id"] for row in rows if row["run_id"]})

        def related(table, fields, *, suffix=""):
            if table not in tables or not runs:
                return []
            query = text(f"SELECT {fields} FROM {table} WHERE config_hash = :h AND run_id IN :runs {suffix}")
            return conn.execute(query.bindparams(bindparam("runs", expanding=True)),
                                {"h": config_hash, "runs": runs}).mappings().all()

        captures = {r["run_id"]: r for r in related(
            "decider_inputs", "id, run_id, prompt_version, model, reasoning_effort, context_json, raw_reply, "
            "user_prompt LIKE '%# SESSION RECOVERY%' AS session_recovery_supplied",
            suffix="AND COALESCE(call_kind, 'decide') = 'decide' ORDER BY id")}
        events = {r["run_id"]: r for r in related(
            "event_risk_snapshots", "run_id, regime, risk_score, macro_window", suffix="ORDER BY id")}
        router = {r["source_input_id"]: {"id": r["id"], "status": r["status"]} for r in related(
            "policy_router_comparisons", "id, source_input_id, status",
            suffix="AND source_kind IN ('live', 'observer') ORDER BY id")}
        screened, served = defaultdict(list), defaultdict(set)
        for r in related("learning_opportunities", "run_id, ticker, features_json",
                         suffix="AND coverage = 'prospective_screener' ORDER BY id"):
            screened[r["run_id"]].append(_screened(r))
        for r in related("policy_graph_hits", "run_id, node_id", suffix="AND agent_type = 'DeciderAgent' AND served"):
            served[r["run_id"]].add(r["node_id"])
    cycles = []
    for row in rows:
        run = row["run_id"]
        capture = captures.get(run, {})
        cycles.append(_cycle(row, capture, events.get(run, {}), screened[run], served[run], router.get(capture.get("id"))))
    return {"cycles": cycles}


def entry_evidence(engine, config_hash):
    """Compact counts for the prompt reviewer, with no account values or reply text."""
    cycles = audit_cycles(engine, config_hash)["cycles"]
    groups = defaultdict(Counter)
    pass_gates = Counter()
    for cycle in cycles:
        group = groups[cycle["version"], cycle["regime"]]
        group["cycles"] += 1
        group["missing_model_replies"] += cycle["model_buys"] is None
        group["cycles_with_zero_model_buys"] += cycle["model_buys"] == 0
        group["confirmed_buy_fills"] += cycle["filled_buys"]
        group["cycles_with_session_recovery"] += bool(cycle["session_recovery_supplied"])
        assessed = {item["ticker"] for item in cycle["decisions"] + cycle["considered"]}
        fresh = [item for item in cycle["screened"] if item["held"] is False]
        group["fresh_screener_rows"] += len(fresh)
        group["fresh_screener_rows_with_assessment"] += sum(item["ticker"] in assessed for item in fresh)
        pass_gates.update(item["cited"][0] for item in cycle["considered"] if item["passed"] and item["cited"])
    return {"scope": "Latest 20 saved decision cycles, including any retries. Model citations and "
                     "assessment coverage describe recorded behavior. They do not measure missed returns or causal effects.",
            "by_policy_version_and_regime": [{"version": version, "regime": regime, **counts}
                                              for (version, regime), counts in groups.items()],
            "top_first_citations_on_pass_or_watch": dict(pass_gates.most_common(6))}
