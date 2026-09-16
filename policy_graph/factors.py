"""World events and market factors as read-time graph nodes (Phase 4, 2026-09-16).

A *factor* is what the world put in front of the Decider on a cycle: the market regime, a scheduled
binary event inside its window (an FOMC decision, a CPI or jobs print, an operator-added event) or a
holding / candidate whose earnings date falls inside the hold window. Factors are never policy text
and never touch the materialized version directories — the same-bytes contract stays intact. They are
rebuilt from the run log on every read:

    policy_graph_runs      the regime the trader read on each cycle (context JSON)
    event_calendar         the macro windows, reconstructed for any past cycle from its date and ET time
    event_risk_snapshots   the macro window and the earnings flags the trader actually served (once
                           the trader records them; absent rows only mean "no earnings factors")
    policy_graph_hits      which guidelines were cited on those cycles and what the Decider did
    trade_outcomes         how the trades entered under a factor closed

Nodes  <P>.factor (group) → <P>.factor.regime.risk_off · <P>.factor.fomc.2026_09_16 · <P>.factor.cpi.2026_09_11
       · <P>.factor.jobs.2026_09_04 · <P>.factor.other.<slug>.<date> · <P>.factor.earnings.tsla.2026_10_21
Edges  factor --triggers--> guideline: the rules / lessons / code blocks that consume it (authored map by
       kind, plus regime words or the ticker in the guideline body) and the guidelines the Decider cited
       while it was active (provenance derived:cited, confidence = share of that factor's cited decisions).
Paths  factor → guideline cited while active → action, and per factor the closed trades entered under it.

stdlib + sqlalchemy.text; config_hash explicit; never imports config or reads os.environ.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from .health import iso, to_datetime
from .model import AGENT_PREFIX, Edge, Node
from .paths import _closed_rows, _hit_rows

FACTOR_SEGMENT = "factor"
REGIME_LABELS = ("RISK-ON", "MIXED", "RISK-OFF")
# factor kind → last id segments of the guidelines that consume it (resolved against the version's nodes,
# rules first). The event kinds all route to the EVENT GATE family.
_EVENT_RULES = ["event_gate", "event_risk", "risk_management", "event_calendar"]
FACTOR_RULES = {
    "regime": ["regime_gate", "regime", "index_regime", "deploy_policy", "harvest", "extension_cap"],
    "fomc": _EVENT_RULES, "cpi": _EVENT_RULES, "jobs": _EVENT_RULES, "other": _EVENT_RULES,
    "earnings": ["event_gate", "event_risk", "event_calendar"],
}
KIND_LABEL = {"regime": "market regime", "fomc": "FOMC decision", "cpi": "CPI print", "jobs": "jobs report",
              "other": "scheduled event", "earnings": "earnings date"}
TOP_CITED_EDGES = 3
ENTRY_LOOKBACK_DAYS = 20
GROUP_BODY = (
    "What the world put in front of the Decider, cycle by cycle: the market regime it read, the scheduled "
    "binary events inside their windows (FOMC decision, CPI / jobs prints, operator-added events) and the "
    "earnings dates of holdings and candidates inside the hold window. Rebuilt from the run log on every "
    "read — never policy text, never a file. Each factor points at the guidelines that consume it and at "
    "the guidelines the Decider actually cited while it was active; the decisions and their outcomes are "
    "in Decision paths below."
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"


def _loose(s: str) -> str:
    return re.sub(r"[_\-\s]", "", (s or "").lower())


def _to_et(at):
    """Naive timestamps in the log are local machine time; the FOMC 2 pm cut-over needs ET."""
    if at is None:
        return None
    try:
        import pytz
        if at.tzinfo is None:
            at = at.astimezone()          # assume local
        return at.astimezone(pytz.timezone("US/Eastern"))
    except Exception:     # noqa: BLE001
        return at


# ----------------------------------------------------------------------------- inputs
def _runs(engine, config_hash: str, agent_type: str, since: datetime) -> list:
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT run_id, decided_at, context FROM policy_graph_runs
                WHERE config_hash = :h AND agent_type = :a
            """), {"h": config_hash, "a": agent_type}).fetchall()
    except Exception:
        return []
    out = []
    for run_id, at, ctx in rows:
        at = to_datetime(at)
        if at is None or at < since or not run_id:
            continue
        try:
            ctx = json.loads(ctx) if isinstance(ctx, str) else (ctx or {})
        except ValueError:
            ctx = {}
        regime = str((ctx or {}).get("regime") or "").upper() or None
        out.append({"run_id": run_id, "at": at, "regime": regime if regime in REGIME_LABELS else None})
    out.sort(key=lambda r: r["at"])
    return out


def _snapshots(engine, config_hash: str, since: datetime) -> dict:
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT run_id, as_of, regime, macro_window, macro_reason, holdings_earnings, watchlist_earnings
                FROM event_risk_snapshots WHERE config_hash = :h
            """), {"h": config_hash}).fetchall()
    except Exception:
        return {}
    out = {}
    for run_id, at, regime, mw, reason, he, we in rows:
        at = to_datetime(at)
        if at is None or at < since or not run_id:
            continue
        def _l(v):
            try:
                return json.loads(v) if isinstance(v, str) else (v or [])
            except ValueError:
                return []
        out[run_id] = {"at": at, "regime": (regime or "").upper() or None, "macro_window": bool(mw), "macro_reason": reason,
                       "holdings_earnings": _l(he), "watchlist_earnings": _l(we)}
    return out


# ----------------------------------------------------------------------------- factors per cycle
def run_factors(at, regime: Optional[str], snap: Optional[dict] = None) -> list:
    """[{key, kind, label, date, ...}] active on one cycle. Macro windows come from the calendar (so past
    cycles get them too); earnings flags only from the recorded snapshot."""
    out = []
    regime = (regime or (snap or {}).get("regime") or "").upper() or None
    if regime in REGIME_LABELS:
        out.append({"key": f"regime.{_slug(regime)}", "kind": "regime", "label": f"Regime {regime}", "date": None,
                    "regime": regime})
    try:
        import event_calendar as ec
        et = _to_et(at)
        statuses = ec.macro_statuses(et.date(), et.time()) if et is not None else {}
    except Exception:     # noqa: BLE001
        statuses = {}
    for kind in ("fomc", "cpi", "jobs"):
        s = statuses.get(kind) or {}
        if s.get("in_window") and s.get("next"):
            out.append({"key": f"{kind}.{_slug(s['next'])}", "kind": kind, "label": f"{s['label']} {s['next']}",
                        "date": s["next"], "phase": "window"})
        elif s.get("just_printed") and s.get("last"):
            out.append({"key": f"{kind}.{_slug(s['last'])}", "kind": kind, "label": f"{s['label']} {s['last']}",
                        "date": s["last"], "phase": "printed"})
    for s in statuses.get("other") or []:
        d = s.get("next") if s.get("in_window") else (s.get("last") if s.get("just_printed") else None)
        if d:
            out.append({"key": f"other.{_slug(s.get('label'))}.{_slug(d)}", "kind": "other", "label": f"{s.get('label')} {d}",
                        "date": d, "phase": "window" if s.get("in_window") else "printed"})
    for bucket, held in (("holdings_earnings", True), ("watchlist_earnings", False)):
        for h in (snap or {}).get(bucket) or []:
            if not isinstance(h, dict) or not h.get("flag") or not h.get("date") or not h.get("ticker"):
                continue
            tk = str(h["ticker"]).upper()
            out.append({"key": f"earnings.{_slug(tk)}.{_slug(h['date'])}", "kind": "earnings",
                        "label": f"{tk} earnings {h['date']}", "date": h["date"], "ticker": tk, "flag": h["flag"],
                        "held": held})
    seen, uniq = set(), []
    for f in out:
        if f["key"] not in seen:
            seen.add(f["key"])
            uniq.append(f)
    return uniq


# ----------------------------------------------------------------------------- report
def factor_report(engine, config_hash: str, agent_type: str = "DeciderAgent", *, days: int = 90, now=None,
                  titles: Optional[dict] = None) -> dict:
    now = now or datetime.now()
    since = now - timedelta(days=int(days))
    titles = titles or {}
    runs = _runs(engine, config_hash, agent_type, since)
    snaps = _snapshots(engine, config_hash, since)
    try:
        hits = _hit_rows(engine, config_hash, agent_type, since)
    except Exception:     # noqa: BLE001 — the hit log is created on the trader's first cycle
        hits = []
    try:
        closed = _closed_rows(engine, config_hash, since)
    except Exception:     # noqa: BLE001
        closed = []

    cited_by_run: dict = defaultdict(list)
    buy_runs: dict = defaultdict(list)          # ticker → [(at, run_id)] with a cited BUY
    for h in hits:
        if h["cited"] and h["run_id"]:
            cited_by_run[h["run_id"]].append(h)
            if h["action"] == "buy" and h["ticker"]:
                buy_runs[str(h["ticker"]).upper()].append((h["at"], h["run_id"]))
    for v in buy_runs.values():
        v.sort()

    factors: dict = {}
    run_factor_keys: dict = {}
    flows_in: Counter = Counter()
    flows_out: Counter = Counter()
    for r in runs:
        active = run_factors(r["at"], r["regime"], snaps.get(r["run_id"]))
        run_factor_keys[r["run_id"]] = [f["key"] for f in active]
        decisions = cited_by_run.get(r["run_id"], [])
        # one decision may cite several guidelines: count decisions once per (ticker, action)
        per_decision = {}
        for h in decisions:
            per_decision.setdefault((h["ticker"], h["action"]), set()).add(h["node_id"])
        if active:                      # guideline → action counted once per cited decision under any factor
            for (tk, action), ids in per_decision.items():
                if action:
                    for nid in ids:
                        flows_out[(nid, action)] += 1
        for f in active:
            rec = factors.setdefault(f["key"], {**f, "runs": set(), "first": r["at"], "last": r["at"],
                                                "actions": Counter(), "cited": Counter(), "tickers": Counter(),
                                                "decisions": 0})
            rec["runs"].add(r["run_id"])
            rec["first"] = min(rec["first"], r["at"])
            rec["last"] = max(rec["last"], r["at"])
            for (tk, action), ids in per_decision.items():
                rec["decisions"] += 1
                if action:
                    rec["actions"][action] += 1
                if tk:
                    rec["tickers"][str(tk).upper()] += 1
                for nid in ids:
                    rec["cited"][nid] += 1
                    flows_in[(f["key"], nid)] += 1

    # closed trades entered under a factor: the last cited BUY of that ticker before the sell
    closed_by: dict = defaultdict(list)
    for c in closed:
        tk = str(c["ticker"] or "").upper()
        entry = None
        for at, run_id in reversed(buy_runs.get(tk, [])):
            if at <= c["at"] and (c["at"] - at) <= timedelta(days=ENTRY_LOOKBACK_DAYS):
                entry = run_id
                break
        if entry is None:
            continue
        for key in run_factor_keys.get(entry, []):
            closed_by[key].append(c)

    def _stats(rows):
        n = len(rows)
        wins = sum(1 for c in rows if (c["gain_pct"] or 0) > 0)
        return {"closed": n, "wins": wins, "losses": n - wins, "win_rate": (wins / n) if n else None,
                "pnl": round(sum(c["gain_amount"] for c in rows), 2),
                "recent": [{"ticker": c["ticker"], "gain_pct": round(float(c["gain_pct"] or 0) * 100.0, 2), "at": iso(c["at"])}
                           for c in sorted(rows, key=lambda c: c["at"], reverse=True)[:5]]}

    kind_rank = {"regime": 0, "fomc": 1, "cpi": 2, "jobs": 3, "other": 4, "earnings": 5}
    items = []
    for key, rec in factors.items():
        q = _stats(closed_by.get(key, []))
        top = [{"id": nid, "title": titles.get(nid, nid), "count": n}
               for nid, n in sorted(rec["cited"].items(), key=lambda kv: (-kv[1], kv[0]))]
        items.append({
            "key": key, "id": key, "kind": rec["kind"], "kind_label": KIND_LABEL.get(rec["kind"], rec["kind"]),
            "label": rec["label"], "date": rec.get("date"), "phase": rec.get("phase"), "ticker": rec.get("ticker"),
            "flag": rec.get("flag"), "held": rec.get("held"), "regime": rec.get("regime"),
            "cycles": len(rec["runs"]), "first": iso(rec["first"]), "last": iso(rec["last"]),
            "decisions": rec["decisions"], "actions": dict(rec["actions"]),
            "tickers": [t for t, _ in rec["tickers"].most_common(6)], "guidelines": top, **q,
        })
    items.sort(key=lambda f: (kind_rank.get(f["kind"], 9), f["date"] or "", f["key"]))
    keys = [f["key"] for f in items]
    guide_ids = sorted({nid for (_k, nid) in flows_in}, key=lambda n: (-sum(v for (k, m), v in flows_in.items() if m == n), n))
    return {
        "agent_type": agent_type, "config_hash": config_hash, "days": int(days), "since": iso(since), "now": iso(now),
        "runs": len(runs), "runs_with_snapshot": sum(1 for r in runs if r["run_id"] in snaps),
        "factors": items, "keys": keys,
        "guidelines": [{"id": n, "title": titles.get(n, n)} for n in guide_ids],
        "actions": sorted({a for (_n, a) in flows_out}),
        "flows_in": [{"source": k, "target": n, "value": v} for (k, n), v in sorted(flows_in.items())],
        "flows_out": [{"source": n, "target": a, "value": v} for (n, a), v in sorted(flows_out.items())],
        "empty": not items,
        "note": (None if items else "No cycles in this window carry a regime or a scheduled event yet; factors appear as "
                 "policy_graph_runs and event_risk_snapshots accumulate."),
    }


# ----------------------------------------------------------------------------- nodes + edges
def _factor_body(f: dict) -> str:
    when = f"active in {f['cycles']} cycle{'s' if f['cycles'] != 1 else ''}"
    if f.get("first"):
        when += f" from {f['first'][:16].replace('T', ' ')} to {f['last'][:16].replace('T', ' ')}"
    acts = " · ".join(f"{n} {a}" for a, n in sorted(f.get("actions", {}).items(), key=lambda kv: -kv[1])) or "none cited"
    guides = ", ".join(f"{g['title']} ×{g['count']}" for g in f.get("guidelines", [])[:5]) or "none"
    head = {
        "regime": f"**Market regime {f.get('regime')}** as read from the INDEX REGIME line (SPY / QQQ vs 20d MA, leader cohort).",
        "fomc": f"**FOMC decision {f.get('date')}** (2:00 pm ET) — {'inside its 2-session window' if f.get('phase') == 'window' else 'just printed'}.",
        "cpi": f"**CPI print {f.get('date')}** (8:30 am ET) — {'the session before' if f.get('phase') == 'window' else 'printed that morning'}.",
        "jobs": f"**Jobs report {f.get('date')}** (8:30 am ET) — {'the session before' if f.get('phase') == 'window' else 'printed that morning'}.",
        "other": f"**{f.get('label')}** — operator-added scheduled event.",
        "earnings": f"**{f.get('ticker')} reports {f.get('date')}** — {'a holding' if f.get('held') else 'a watchlist candidate'} "
                    f"{'reporting within 2 sessions' if f.get('flag') == 'reports_within_2' else 'inside the 5-session hold window'}.",
    }.get(f["kind"], f["label"])
    q = ""
    if f.get("closed"):
        wr = f"{round((f.get('win_rate') or 0) * 100)}%"
        q = (f"\n- Closed trades entered under it: {f['closed']} ({f['wins']}W/{f['losses']}L), win rate {wr}, "
             f"P&L {'+' if f['pnl'] >= 0 else '−'}${abs(f['pnl']):.0f}.")
    return (f"{head}\n- {when.capitalize()}.\n- Decisions while active: {acts} ({f.get('decisions', 0)} cited decisions"
            f"{', tickers ' + ', '.join(f['tickers']) if f.get('tickers') else ''}).\n- Guidelines cited: {guides}.{q}\n"
            f"- Source: run log (regime), the event calendar (windows), event_risk_snapshots (earnings flags), the hit log, "
            f"trade_outcomes. Not a file — rebuilt on every read.")


def factor_nodes(report: dict, version_nodes: dict, agent_type: str = "DeciderAgent") -> tuple:
    """(nodes, edges) for the graph payload. Edges only point at guidelines present in `version_nodes`."""
    prefix = AGENT_PREFIX[agent_type]
    items = report.get("factors") or []
    if not items:
        return [], []
    group_id = f"{prefix}.{FACTOR_SEGMENT}"
    stamp = f"{agent_type}.factors.{report.get('days')}d"

    def _node(node_id, title, body, order, extra):
        return Node(id=node_id, agent=agent_type, title=title, node_type="factor",
                    parent=(f"{prefix}.root" if node_id == group_id else group_id), field=None, body=body,
                    sep_before="", sep_after="", order=order, polarity="structure", polarity_source="override",
                    owner="world", status="generated", compiled="never", locked=True, provenance="derived:runs",
                    tags=[], tickers=([extra["ticker"]] if extra.get("ticker") else []), links=[], extra=extra)

    nodes = [_node(group_id, "World events & market factors", GROUP_BODY, 0,
                   {"days": report.get("days"), "cycles": report.get("runs"), "count": len(items)})]
    edges: list = []
    seen: set = set()

    def add(source, target, *, provenance, confidence=1.0, via=None):
        key = (source, target, "triggers")
        if target not in version_nodes or source == target:
            return
        if key in seen:               # an authored edge keeps its provenance but learns the cited count
            if via:
                for e in edges:
                    if e.key() == key and not e.via:
                        e.via = via
            return
        seen.add(key)
        edges.append(Edge(source=source, target=target, edge_type="triggers", confidence=confidence,
                          provenance=provenance, version=stamp, via=via))

    by_last: dict = defaultdict(list)
    for n in version_nodes.values():
        by_last[_loose(n.id.split(".")[-1])].append(n)
    try:
        from .assembly import _mentions_regime
    except Exception:     # noqa: BLE001
        _mentions_regime = None

    for order, f in enumerate(items, start=1):
        fid = f"{group_id}.{f['key']}"
        extra = {k: f.get(k) for k in ("kind", "kind_label", "date", "phase", "ticker", "flag", "held", "regime", "cycles",
                                       "first", "last", "decisions", "actions", "closed", "wins", "losses", "win_rate", "pnl")}
        extra["guidelines"] = f.get("guidelines", [])[:8]
        nodes.append(_node(fid, f["label"], _factor_body(f), order, extra))
        for slug in FACTOR_RULES.get(f["kind"], []):
            hits = sorted(by_last.get(_loose(slug), []), key=lambda n: (n.node_type != "rule", n.id))
            for n in hits[:1]:
                add(fid, n.id, provenance="authored:factor_map")
        if f["kind"] == "regime" and _mentions_regime is not None:
            for n in version_nodes.values():
                if n.node_type in ("rule", "lesson", "entry") and n.owner in ("db", "default-file") \
                        and _mentions_regime(n.body or "", f.get("regime") or ""):
                    add(fid, n.id, provenance="derived:regime_word", confidence=0.8)
        if f.get("ticker"):
            for n in version_nodes.values():
                if f["ticker"] in {str(t).upper() for t in (n.tickers or [])} and n.owner in ("db", "default-file", "decider_memory"):
                    add(fid, n.id, provenance="derived:ticker", confidence=0.8)
        total = sum(g["count"] for g in f.get("guidelines", [])) or 1
        for g in f.get("guidelines", [])[:TOP_CITED_EDGES]:
            add(fid, g["id"], provenance="derived:cited", confidence=round(g["count"] / total, 3), via=f"cited {g['count']}×")
    return nodes, edges


def factor_payload_for_node(report: dict, node_id: str, agent_type: str = "DeciderAgent") -> Optional[dict]:
    """The details-panel payload for one factor node (or the group)."""
    prefix = AGENT_PREFIX[agent_type]
    group_id = f"{prefix}.{FACTOR_SEGMENT}"
    if node_id == group_id:
        return {"node_kind": "group", "cycles": report.get("runs"), "days": report.get("days"),
                "count": len(report.get("factors") or []), "runs_with_snapshot": report.get("runs_with_snapshot")}
    key = node_id[len(group_id) + 1:] if node_id.startswith(group_id + ".") else None
    for f in report.get("factors") or []:
        if f["key"] == key:
            return {**f, "node_kind": "factor"}
    return None


__all__ = ["factor_report", "factor_nodes", "factor_payload_for_node", "run_factors", "FACTOR_RULES", "FACTOR_SEGMENT"]
