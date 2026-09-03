"""Guideline citations — which guidelines drove a decision (Phase 2, step 6).

The Decider may return `"cited": ["DA.directives.strategy.priced_kill", ...]` on each decision.
The trader folds that list into the decision's `reason` as a trailing ` [cites: id, id]` suffix
(`append_cites`), so nothing downstream changes shape: `trade_decisions.data[*].reason`,
`holdings.reason` and `trade_outcomes.original_reason` all carry the citation with the text.
`parse_cites` / `strip_cites` read it back; `guideline_index` renders the id list the Decider is
shown; `citation_health` joins decisions and closed trades back to one guideline id.

stdlib + `sqlalchemy.text`; never imports config; config_hash is explicit.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from sqlalchemy import text

from .model import COMPILED_FIELDS, ID_RE, Version

CITE_RE = re.compile(r"\s*\[cites?:\s*([^\]]*)\]\s*$", re.I)
MAX_CITES = 6
CITABLE_TYPES = ("section", "rule", "lesson", "entry", "reminder", "identity", "note", "code")
SYNCED_REASON = "Schwab synced position"


# ----------------------------------------------------------------------------- reason suffix
def parse_cites(reason) -> list:
    """Guideline ids cited in a reason (empty when none)."""
    m = CITE_RE.search(str(reason or ""))
    if not m:
        return []
    return normalize_ids(re.split(r"[,\s]+", m.group(1)))


def strip_cites(reason) -> str:
    return CITE_RE.sub("", str(reason or "")).rstrip()


def split_cites(reason) -> tuple:
    """(reason without the suffix, [ids])."""
    return strip_cites(reason), parse_cites(reason)


def append_cites(reason, ids: Iterable) -> str:
    """Reason text with ` [cites: …]` appended (replacing an existing suffix; unchanged when no ids)."""
    base = strip_cites(reason)
    clean = normalize_ids(ids)
    if not clean:
        return base
    return f"{base} [cites: {', '.join(clean)}]".strip()


def normalize_ids(raw, known: Optional[Iterable] = None) -> list:
    """Valid, de-duplicated guideline ids (prefix upper-cased, rest lower-cased), at most MAX_CITES,
    restricted to `known` when given."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    known_set = set(known) if known is not None else None
    out: list = []
    for item in raw:
        s = str(item or "").strip().strip("[]\"'`")
        if not s:
            continue
        head, _, tail = s.partition(".")
        s = f"{head.upper()}.{tail.lower()}" if tail else s.upper()
        if not ID_RE.match(s):
            continue
        if known_set is not None and s not in known_set:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= MAX_CITES:
            break
    return out


def fold_into_decisions(decisions, known: Optional[Iterable] = None) -> list:
    """Move each decision's `cited` list into its reason suffix (in place). Returns the ids used."""
    used: list = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        raw = d.pop("cited", None)
        if raw is None:
            raw = d.pop("cites", None)
        ids = normalize_ids(raw, known)
        if not ids:
            continue
        d["reason"] = append_cites(d.get("reason") or "", ids)
        used.extend(i for i in ids if i not in used)
    return used


# ----------------------------------------------------------------------------- what the Decider sees
def citable_nodes(version: Version) -> list:
    """[(id, title)] of the guidelines a decision may cite: stored / inherited guidelines of the
    three evolving fields (sections and their rules, lessons, log entries) plus the code-owned
    blocks that fire for this version; in compile order, code blocks last."""
    out = []
    order = version.manifest.get("compile_order") or {}
    fields_meta = version.manifest.get("fields") or {}
    for f in COMPILED_FIELDS:
        ids = list(order.get(f) or [])
        if (fields_meta.get(f) or {}).get("inherited"):
            ids = [n.id for n in sorted((x for x in version.nodes.values() if x.field == f and x.owner == "default-file"),
                                        key=lambda n: (n.order, n.id))]
        for i in ids:
            n = version.nodes.get(i)
            if n is None or n.node_type not in CITABLE_TYPES or not (n.body or "").strip():
                continue
            out.append((n.id, n.title or n.id))
    fires = (version.manifest.get("code") or {}).get("fires") or {}
    code = [n for n in version.nodes.values() if n.owner == "code" and n.node_type == "code"
            and fires.get(n.id, n.extra.get("fires", True)) and (n.body or "").strip()]
    for n in sorted(code, key=lambda n: (n.order, n.id)):
        out.append((n.id, n.title or n.id))
    return out


def guideline_index(version: Version) -> str:
    """One line per citable guideline: `id — title`."""
    return "\n".join(f"{i} — {t}" for i, t in citable_nodes(version))


# ----------------------------------------------------------------------------- health
def _decision_rows(engine, config_hash: str) -> list:
    """(timestamp, decision dict) for every stored decision whose reason carries a citation."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT timestamp, data FROM trade_decisions
            WHERE config_hash = :h AND CAST(data AS TEXT) LIKE '%[cites:%'
            ORDER BY timestamp DESC
        """), {"h": config_hash}).fetchall()
    out = []
    for r in rows:
        data = r[1]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if isinstance(data, dict):
            data = data.get("decisions") or []
        for d in data or []:
            if isinstance(d, dict) and d.get("action") and "[cites" in str(d.get("reason") or ""):
                out.append((r[0], d))
    return out


def citation_health(engine, config_hash: str, node_id: str, *, recent: int = 8) -> dict:
    """How one guideline has been used: decisions that cited it and the closed trades whose buy
    reason cited it (`trade_outcomes.original_reason`)."""
    decisions = [(ts, d) for ts, d in _decision_rows(engine, config_hash) if node_id in parse_cites(d.get("reason"))]
    by_action: dict = {}
    for _ts, d in decisions:
        a = str(d.get("action") or "").lower()
        by_action[a] = by_action.get(a, 0) + 1
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, sell_timestamp, gain_loss_percentage, gain_loss_amount, original_reason, sell_reason
            FROM trade_outcomes
            WHERE config_hash = :h AND original_reason LIKE '%[cites:%' AND original_reason NOT LIKE :synced
            ORDER BY sell_timestamp DESC
        """), {"h": config_hash, "synced": f"%{SYNCED_REASON}%"}).fetchall()
    closed = [r for r in rows if node_id in parse_cites(r[4])]
    wins = sum(1 for r in closed if (r[2] or 0) > 0)
    pnl = float(sum(float(r[3] or 0) for r in closed))
    pct = [float(r[2]) for r in closed if r[2] is not None]
    return {
        "node_id": node_id,
        "decisions": len(decisions), "by_action": by_action,
        "closed": len(closed), "wins": wins, "losses": len(closed) - wins,
        "win_rate": (wins / len(closed)) if closed else None,
        "avg_gain_pct": (sum(pct) / len(pct)) if pct else None,
        "pnl": pnl,
        "recent_decisions": [{"timestamp": (ts.isoformat() if hasattr(ts, "isoformat") else str(ts)),
                              "ticker": d.get("ticker"), "action": d.get("action")} for ts, d in decisions[:recent]],
        "recent_closed": [{"ticker": r[0], "sell_timestamp": (r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1])),
                           "gain_pct": r[2], "gain_amount": r[3]} for r in closed[:recent]],
    }


# ----------------------------------------------------------------------------- hit log (per run, per guideline)
# One row per guideline per decision run: `served` = it was in the prompt (with the route that
# selected it), `cited` = a decision cited it (with the ticker / action). Windows over decided_at
# give the "N hits in 7d / 30d / 90d / 1y" importance figures; routes give route importance.
DDL_HITS_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_graph_hits (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    agent_type TEXT NOT NULL,
    prompt_version INTEGER,
    run_id TEXT,
    decided_at TIMESTAMP,
    node_id TEXT NOT NULL,
    route TEXT,
    served BOOLEAN DEFAULT FALSE,
    cited BOOLEAN DEFAULT FALSE,
    ticker TEXT,
    action TEXT
)
"""
DDL_HITS_SQLITE = DDL_HITS_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
WINDOWS = (("7d", 7), ("30d", 30), ("90d", 90), ("1y", 365))


def ensure_hits_schema(engine) -> None:
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    with engine.begin() as conn:
        conn.execute(text(DDL_HITS_POSTGRES if dialect == "postgresql" else DDL_HITS_SQLITE))
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_policy_graph_hits_node ON policy_graph_hits (config_hash, node_id, decided_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_policy_graph_hits_run ON policy_graph_hits (config_hash, run_id)"))
        except Exception:     # noqa: BLE001 — index creation is best effort
            pass


def record_served(engine, config_hash: str, agent_type: str, prompt_version, run_id: str, served, *, decided_at=None) -> int:
    """Insert one served row per (node_id, route) for this run. `served` = [(node_id, route)] or
    objects with .node_id/.route. Returns the row count."""
    rows = []
    seen = set()
    for item in served or []:
        nid = getattr(item, "node_id", None) or (item[0] if isinstance(item, (tuple, list)) else None)
        route = getattr(item, "route", None) or (item[1] if isinstance(item, (tuple, list)) and len(item) > 1 else None)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        rows.append({"h": config_hash, "a": agent_type, "v": prompt_version, "r": run_id,
                     "t": decided_at or _now(), "n": nid, "route": route})
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO policy_graph_hits (config_hash, agent_type, prompt_version, run_id, decided_at, node_id, route, served, cited)
            VALUES (:h, :a, :v, :r, :t, :n, :route, :served, :cited)
        """), [dict(r, served=True, cited=False) for r in rows])
    return len(rows)


def record_cited(engine, config_hash: str, agent_type: str, prompt_version, run_id: str, decisions, *, decided_at=None) -> int:
    """Mark the guideline ids cited by each decision of this run (rows exist when the id was served;
    an id cited without being served gets its own row with route 'unserved')."""
    hits = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        for nid in parse_cites(d.get("reason")):
            hits.append((nid, str(d.get("ticker") or "").upper() or None, str(d.get("action") or "").lower() or None))
    if not hits:
        return 0
    n = 0
    with engine.begin() as conn:
        for nid, ticker, action in hits:
            res = conn.execute(text("""
                UPDATE policy_graph_hits SET cited = :cited, ticker = COALESCE(ticker, :tk), action = COALESCE(action, :ac)
                WHERE config_hash = :h AND run_id = :r AND node_id = :n AND served = :served
            """), {"cited": True, "served": True, "tk": ticker, "ac": action, "h": config_hash, "r": run_id, "n": nid})
            if getattr(res, "rowcount", 0):
                n += 1
                continue
            conn.execute(text("""
                INSERT INTO policy_graph_hits (config_hash, agent_type, prompt_version, run_id, decided_at, node_id, route, served, cited, ticker, action)
                VALUES (:h, :a, :v, :r, :t, :n, 'unserved', :served, :cited, :tk, :ac)
            """), {"h": config_hash, "a": agent_type, "v": prompt_version, "r": run_id, "t": decided_at or _now(),
                   "n": nid, "served": False, "cited": True, "tk": ticker, "ac": action})
            n += 1
    return n


def _now():
    from datetime import datetime
    return datetime.now()


def _windows(now=None):
    from datetime import datetime, timedelta
    now = now or datetime.now()
    return [(label, now - timedelta(days=days)) for label, days in WINDOWS]


def hit_counts(engine, config_hash: str, node_id: str, *, now=None) -> dict:
    """{window: {served, cited, closed, wins, win_rate, pnl}} plus {"routes": {route: cited}} for
    one guideline. Closed trades come from trade_outcomes (buy reasons carrying the citation)."""
    out: dict = {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT decided_at, route, served, cited FROM policy_graph_hits
            WHERE config_hash = :h AND node_id = :n
        """), {"h": config_hash, "n": node_id}).fetchall()
        outcomes = conn.execute(text("""
            SELECT sell_timestamp, gain_loss_percentage, gain_loss_amount, original_reason
            FROM trade_outcomes
            WHERE config_hash = :h AND original_reason LIKE '%[cites:%' AND original_reason NOT LIKE :synced
        """), {"h": config_hash, "synced": f"%{SYNCED_REASON}%"}).fetchall()
    from .health import to_datetime
    closed = [(to_datetime(r[0]), r[1], r[2]) for r in outcomes if node_id in parse_cites(r[3])]
    routes: dict = {}
    for label, since in _windows(now):
        served = cited = 0
        for r in rows:
            at = to_datetime(r[0])
            if at is None or at < since:
                continue
            if r[2]:
                served += 1
            if r[3]:
                cited += 1
        win = [c for c in closed if c[0] is not None and c[0] >= since]
        wins = sum(1 for c in win if (c[1] or 0) > 0)
        out[label] = {"served": served, "cited": cited, "closed": len(win), "wins": wins,
                      "win_rate": (wins / len(win)) if win else None,
                      "pnl": float(sum(float(c[2] or 0) for c in win))}
    for r in rows:
        if r[3]:
            routes[r[1] or "?"] = routes.get(r[1] or "?", 0) + 1
    out["routes"] = routes
    return out


def hit_map(engine, config_hash: str, *, now=None) -> dict:
    """{node_id: {"cited_7d", "cited_30d", "cited_90d", "cited_1y", "served_90d"}} for every guideline
    with any row — one query, for graph sizing."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT node_id, decided_at, served, cited FROM policy_graph_hits WHERE config_hash = :h
        """), {"h": config_hash}).fetchall()
    from .health import to_datetime
    wins = _windows(now)
    out: dict = {}
    for nid, at, served, cited in rows:
        at = to_datetime(at)
        if at is None:
            continue
        d = out.setdefault(nid, {"cited_7d": 0, "cited_30d": 0, "cited_90d": 0, "cited_1y": 0, "served_90d": 0})
        for label, since in wins:
            if at >= since:
                if cited:
                    d[f"cited_{label}"] += 1
                if served and label == "90d":
                    d["served_90d"] += 1
    return out


def health_for_prompt(engine, config_hash: str, node_ids, *, now=None) -> dict:
    """{node_id: {"7d": {...}, "30d": {...}, "90d": {...}}} for the ids in `node_ids` — the
    figures rendered next to each guideline; empty when the guideline has no record."""
    ids = set(node_ids or [])
    if not ids:
        return {}
    m = hit_map(engine, config_hash, now=now)
    with engine.connect() as conn:
        outcomes = conn.execute(text("""
            SELECT sell_timestamp, gain_loss_percentage, original_reason FROM trade_outcomes
            WHERE config_hash = :h AND original_reason LIKE '%[cites:%' AND original_reason NOT LIKE :synced
        """), {"h": config_hash, "synced": f"%{SYNCED_REASON}%"}).fetchall()
    from .health import to_datetime
    since90 = dict(_windows(now))["90d"]
    closed_by: dict = {}
    for r in outcomes:
        at = to_datetime(r[0])
        if at is None or at < since90:
            continue
        for nid in parse_cites(r[2]):
            if nid in ids:
                c = closed_by.setdefault(nid, [0, 0])
                c[0] += 1
                if (r[1] or 0) > 0:
                    c[1] += 1
    out = {}
    for nid in ids:
        h = m.get(nid)
        c = closed_by.get(nid)
        if not h and not c:
            continue
        entry = {}
        for w in ("7d", "30d", "90d"):
            entry[w] = {"cited": (h or {}).get(f"cited_{w}", 0)}
        if c:
            entry["90d"].update({"closed": c[0], "wins": c[1], "win_rate": (c[1] / c[0]) if c[0] else None})
        out[nid] = entry
    return out


def backfill_hits_from_decisions(engine, config_hash: str, agent_type: str = "DeciderAgent") -> int:
    """Create 'unserved' cited rows for historical decisions whose reasons carry citations but
    have no hit row yet (decisions made before the hit log existed). Idempotent."""
    ensure_hits_schema(engine)
    with engine.connect() as conn:
        have = {(r[0], r[1]) for r in conn.execute(text(
            "SELECT run_id, node_id FROM policy_graph_hits WHERE config_hash = :h"), {"h": config_hash}).fetchall()}
        rows = conn.execute(text("""
            SELECT run_id, timestamp, data FROM trade_decisions
            WHERE config_hash = :h AND CAST(data AS TEXT) LIKE '%[cites:%'
        """), {"h": config_hash}).fetchall()
    inserts = []
    for run_id, ts, data in rows:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if isinstance(data, dict):
            data = data.get("decisions") or []
        for d in data or []:
            if not isinstance(d, dict):
                continue
            for nid in parse_cites(d.get("reason")):
                if (run_id, nid) in have:
                    continue
                have.add((run_id, nid))
                inserts.append({"h": config_hash, "a": agent_type, "r": run_id, "t": ts, "n": nid,
                                "tk": str(d.get("ticker") or "").upper() or None, "ac": str(d.get("action") or "").lower() or None})
    if inserts:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO policy_graph_hits (config_hash, agent_type, prompt_version, run_id, decided_at, node_id, route, served, cited, ticker, action)
                VALUES (:h, :a, NULL, :r, :t, :n, 'unserved', :served, :cited, :tk, :ac)
            """), [dict(i, served=False, cited=True) for i in inserts])
    return len(inserts)


# ----------------------------------------------------------------------------- run log (trim size per cycle)
DDL_RUNS_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_graph_runs (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    agent_type TEXT NOT NULL,
    prompt_version INTEGER,
    run_id TEXT,
    decided_at TIMESTAMP,
    served INTEGER,
    dropped INTEGER,
    chars_full INTEGER,
    chars_served INTEGER,
    routes TEXT,
    context TEXT
)
"""
DDL_RUNS_SQLITE = DDL_RUNS_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")


def ensure_runs_schema(engine) -> None:
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    with engine.begin() as conn:
        conn.execute(text(DDL_RUNS_POSTGRES if dialect == "postgresql" else DDL_RUNS_SQLITE))


def record_run(engine, config_hash: str, agent_type: str, prompt_version, run_id: str, *, served: int, dropped: int,
               chars_full: int, chars_served: int, routes: dict, context: dict, decided_at=None) -> None:
    ensure_runs_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO policy_graph_runs (config_hash, agent_type, prompt_version, run_id, decided_at, served, dropped,
                chars_full, chars_served, routes, context)
            VALUES (:h, :a, :v, :r, :t, :s, :d, :cf, :cs, :routes, :ctx)
        """), {"h": config_hash, "a": agent_type, "v": prompt_version, "r": run_id, "t": decided_at or _now(),
               "s": int(served), "d": int(dropped), "cf": int(chars_full), "cs": int(chars_served),
               "routes": json.dumps(routes or {}, sort_keys=True), "ctx": json.dumps(context or {}, sort_keys=True)})


def run_stats(engine, config_hash: str, agent_type: str, *, limit: int = 30) -> Optional[dict]:
    """Trim statistics over the last `limit` runs: the latest run plus averages — how much of the
    full guideline text the graph query served."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT decided_at, prompt_version, run_id, served, dropped, chars_full, chars_served, routes, context
            FROM policy_graph_runs WHERE config_hash = :h AND agent_type = :a
            ORDER BY id DESC LIMIT :lim
        """), {"h": config_hash, "a": agent_type, "lim": int(limit)}).fetchall()
    if not rows:
        return None
    from .health import iso
    latest = rows[0]
    n = len(rows)
    avg_served = sum(r[3] or 0 for r in rows) / n
    avg_dropped = sum(r[4] or 0 for r in rows) / n
    avg_full = sum(r[5] or 0 for r in rows) / n
    avg_out = sum(r[6] or 0 for r in rows) / n
    route_totals: dict = {}
    for r in rows:
        try:
            for k, v in (json.loads(r[7] or "{}")).items():
                route_totals[k] = route_totals.get(k, 0) + int(v)
        except ValueError:
            pass
    return {
        "runs": n,
        "latest": {"decided_at": iso(latest[0]), "prompt_version": latest[1], "run_id": latest[2], "served": latest[3],
                   "dropped": latest[4], "chars_full": latest[5], "chars_served": latest[6],
                   "ratio": (latest[6] / latest[5]) if latest[5] else None,
                   "routes": (json.loads(latest[7]) if latest[7] else {}), "context": (json.loads(latest[8]) if latest[8] else {})},
        "average": {"served": avg_served, "dropped": avg_dropped, "chars_full": avg_full, "chars_served": avg_out,
                    "ratio": (avg_out / avg_full) if avg_full else None},
        "routes": route_totals,
    }


__all__ = ["CITE_RE", "MAX_CITES", "WINDOWS", "ensure_hits_schema", "ensure_runs_schema", "record_run", "run_stats",
           "DDL_RUNS_POSTGRES", "record_served", "record_cited", "hit_counts",
           "hit_map", "health_for_prompt", "backfill_hits_from_decisions", "DDL_HITS_POSTGRES", "parse_cites", "strip_cites", "split_cites", "append_cites", "normalize_ids",
           "fold_into_decisions", "citable_nodes", "guideline_index", "citation_health"]
