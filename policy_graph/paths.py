"""Decision paths — what the hit log says about how guidelines are used (offline-style analysis
served live on the Policy Graph tab).

A decision's path is  context → route that served a guideline → guideline cited → action → outcome.
Two views over one window (days):

  frequency  route → guideline → action, weighted by cited decisions (a three-column flow);
             plus the guidelines cited without being served (the query missed them) and the
             ones served but never cited (dead weight in the prompt)
  quality    per guideline: cited decisions, closed trades whose buy reason cited it, win rate,
             P&L, and the guidelines most often co-cited on its winners and its losers

Inputs: policy_graph_hits (served / cited per run), trade_outcomes (buy reasons carry
` [cites: …]`), trade_decisions (co-citation within one decision). stdlib + sqlalchemy.text;
config_hash explicit; never imports config.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from .citations import SYNCED_REASON, parse_cites
from .health import iso, to_datetime

WINDOWS = (30, 90, 365)
TOP_GUIDELINES = 14
TOP_PAIRS = 3


def _hit_rows(engine, config_hash: str, agent_type: str, since: datetime) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT run_id, decided_at, node_id, route, served, cited, ticker, action
            FROM policy_graph_hits WHERE config_hash = :h AND agent_type = :a
        """), {"h": config_hash, "a": agent_type}).fetchall()
    out = []
    for r in rows:
        at = to_datetime(r[1])
        if at is None or at < since:
            continue
        out.append({"run_id": r[0], "at": at, "node_id": r[2], "route": r[3] or "?", "served": bool(r[4]),
                    "cited": bool(r[5]), "ticker": r[6], "action": (r[7] or "").lower() or None})
    return out


def _closed_rows(engine, config_hash: str, since: datetime) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, original_reason
            FROM trade_outcomes
            WHERE config_hash = :h AND original_reason LIKE '%[cites:%' AND original_reason NOT LIKE :synced
        """), {"h": config_hash, "synced": f"%{SYNCED_REASON}%"}).fetchall()
    out = []
    for r in rows:
        at = to_datetime(r[1])
        if at is None or at < since:
            continue
        ids = parse_cites(r[4])
        if ids:
            out.append({"ticker": r[0], "at": at, "gain_pct": r[2], "gain_amount": float(r[3] or 0), "cites": ids})
    return out


def _decision_cites(engine, config_hash: str, since: datetime) -> list:
    """[[ids cited together in one decision], …] for co-citation."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT timestamp, data FROM trade_decisions
            WHERE config_hash = :h AND CAST(data AS TEXT) LIKE '%[cites:%'
        """), {"h": config_hash}).fetchall()
    out = []
    for ts, data in rows:
        at = to_datetime(ts)
        if at is None or at < since:
            continue
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if isinstance(data, dict):
            data = data.get("decisions") or []
        for d in data or []:
            if isinstance(d, dict):
                ids = parse_cites(d.get("reason"))
                if ids:
                    out.append({"ids": ids, "action": str(d.get("action") or "").lower(), "ticker": d.get("ticker")})
    return out


def path_report(engine, config_hash: str, agent_type: str = "DeciderAgent", *, days: int = 90, now=None,
                titles: Optional[dict] = None) -> dict:
    now = now or datetime.now()
    days = int(days) if int(days) in WINDOWS else 90
    since = now - timedelta(days=days)
    titles = titles or {}
    hits = _hit_rows(engine, config_hash, agent_type, since)
    closed = _closed_rows(engine, config_hash, since)
    decisions = _decision_cites(engine, config_hash, since)

    runs = {h["run_id"] for h in hits if h["run_id"]}
    served_by: dict = {}
    cited_by: dict = {}
    route_node: dict = {}
    node_action: dict = {}
    for h in hits:
        if h["served"]:
            served_by[h["node_id"]] = served_by.get(h["node_id"], 0) + 1
        if h["cited"]:
            cited_by[h["node_id"]] = cited_by.get(h["node_id"], 0) + 1
            route_node[(h["route"], h["node_id"])] = route_node.get((h["route"], h["node_id"]), 0) + 1
            if h["action"]:
                node_action[(h["node_id"], h["action"])] = node_action.get((h["node_id"], h["action"]), 0) + 1

    top = sorted(cited_by, key=lambda n: (-cited_by[n], n))[:TOP_GUIDELINES]
    top_set = set(top)
    flows_in = [{"source": r, "target": n, "value": v} for (r, n), v in sorted(route_node.items()) if n in top_set]
    flows_out = [{"source": n, "target": a, "value": v} for (n, a), v in sorted(node_action.items()) if n in top_set]
    routes = sorted({f["source"] for f in flows_in})
    actions = sorted({f["target"] for f in flows_out})

    unserved = sorted((n for n in cited_by if any(h["node_id"] == n and h["route"] == "unserved" for h in hits)),
                      key=lambda n: -cited_by[n])
    dead = sorted((n for n in served_by if not cited_by.get(n)), key=lambda n: (-served_by[n], n))

    # quality
    wins_by: dict = {}
    closed_by: dict = {}
    pnl_by: dict = {}
    co_win: dict = {}
    co_loss: dict = {}
    for c in closed:
        win = (c["gain_pct"] or 0) > 0
        for n in c["cites"]:
            closed_by[n] = closed_by.get(n, 0) + 1
            pnl_by[n] = pnl_by.get(n, 0.0) + c["gain_amount"]
            if win:
                wins_by[n] = wins_by.get(n, 0) + 1
            bucket = co_win if win else co_loss
            for m in c["cites"]:
                if m != n:
                    bucket.setdefault(n, {})
                    bucket[n][m] = bucket[n].get(m, 0) + 1
    co_dec: dict = {}
    for d in decisions:
        for n in d["ids"]:
            for m in d["ids"]:
                if m != n:
                    co_dec.setdefault(n, {})
                    co_dec[n][m] = co_dec[n].get(m, 0) + 1

    def _top_pairs(table: dict, n: str) -> list:
        items = sorted((table.get(n) or {}).items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_PAIRS]
        return [{"id": m, "title": titles.get(m, m), "count": k} for m, k in items]

    quality = []
    for n in sorted(set(cited_by) | set(closed_by), key=lambda n: (-(closed_by.get(n, 0)), -(cited_by.get(n, 0)), n)):
        cl = closed_by.get(n, 0)
        w = wins_by.get(n, 0)
        quality.append({
            "id": n, "title": titles.get(n, n), "cited": cited_by.get(n, 0), "served": served_by.get(n, 0),
            "closed": cl, "wins": w, "losses": cl - w, "win_rate": (w / cl) if cl else None,
            "pnl": round(pnl_by.get(n, 0.0), 2),
            "co_cited": _top_pairs(co_dec, n), "co_on_wins": _top_pairs(co_win, n), "co_on_losses": _top_pairs(co_loss, n),
        })

    total_closed = len(closed)
    total_wins = sum(1 for c in closed if (c["gain_pct"] or 0) > 0)
    return {
        "agent_type": agent_type, "config_hash": config_hash, "days": days, "since": iso(since), "now": iso(now),
        "runs": len(runs), "decisions_cited": len(decisions), "closed_cited": total_closed,
        "win_rate": (total_wins / total_closed) if total_closed else None,
        "frequency": {
            "routes": routes, "guidelines": [{"id": n, "title": titles.get(n, n), "cited": cited_by[n], "served": served_by.get(n, 0)} for n in top],
            "actions": actions, "flows_in": flows_in, "flows_out": flows_out,
            "cited_unserved": [{"id": n, "title": titles.get(n, n), "cited": cited_by[n]} for n in unserved],
            "served_never_cited": [{"id": n, "title": titles.get(n, n), "served": served_by[n]} for n in dead[:TOP_GUIDELINES]],
            "served_never_cited_total": len(dead),
        },
        "quality": quality,
        "empty": not hits and not closed,
        "note": (None if hits or closed else
                 "No cited decisions in this window yet. The trader logs which guidelines it served and which the "
                 "Decider cited on every cycle; paths appear here as those rows and their closed trades accumulate."),
    }


__all__ = ["path_report", "WINDOWS", "TOP_GUIDELINES"]
