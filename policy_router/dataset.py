"""The labeled dataset, rebuilt read-only from the logs — one CycleRecord per logged Decider cycle.

Sources per cycle (run_id), oldest first:
    policy_graph_runs     the cycle list, prompt version, regime (context JSON holds counts + regime)
    policy_graph_hits     what today's assembly served (and the memory rows injected, route 'ltm') and
                          what decisions cited
    trade_decisions       decision reasons and the considered/rejected setups (labels; holdings fallback)
    summaries             the cycle's news (context chunks, news tickers)
    momentum_snapshots    entities (company extraction + holdings) and trend tickers, when the table exists
    event_risk_snapshots  holdings / watchlist tickers and the EVENT CALENDAR block, when it exists
    trade_outcomes        the re-entry quarantine (sells within 2 sessions before the cycle)
    decider_inputs        EXACT cycle inputs when that table exists (feature-detected; the 'decide' call's
                          row, never the citation-repair row; it wins over the reconstruction field by field)
plus the materialized policy version directory (agents/decider/policy-graph/<hash>/v<N>) for the nodes:
diary entries, lessons and the DA.ltm.<id> overlay (active memory rows at that version).

Reconstruction caveats (recorded per cycle in `source`): the watchlist is known only from cycles with
an event snapshot (it is empty otherwise — never taken from the considered setups, which are labels);
holdings fall back to the tickers the cycle held or sold.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import bindparam, inspect, text

from .features import CycleContext, parse_summary_row, tickers_in_summaries
from .labels import parse_decisions
from .nodes import version_nodes

PINNED_TYPES = ("section", "rule", "reminder", "identity", "note", "code")
DECIDER_INPUT_KEYS = {
    "regime": ("regime", "index_regime", "regime_label"),
    "holdings": ("holdings", "holding_tickers"),
    "watchlist": ("watchlist", "watchlist_tickers", "contrarian_watchlist"),
    "quarantined": ("quarantined", "quarantine"),
    "news": ("news", "news_tickers"),
    "entities": ("entities", "entity_tickers"),
    "trend": ("trend", "trend_tickers"),
    "summaries": ("summaries", "parsed_summaries"),
    "event_block": ("event_block", "event_calendar", "event_calendar_block"),
}


@dataclass
class CycleRecord:
    run_id: str
    decided_at: datetime
    prompt_version: int
    ctx: CycleContext
    reasons: list
    pairs: list                                   # [(reason, [cited ids])]
    cited: set
    decided_tickers: set
    nodes: list                                   # [RouterNode] candidates
    today_ids: set                                # routable ids today's assembly / memory sort served
    node_texts: dict = dc_field(default_factory=dict)   # every node id of the version → body (theta pairs)
    node_types: dict = dc_field(default_factory=dict)   # every node id of the version → node_type
    source: dict = dc_field(default_factory=dict)

    def pinned_ids(self, routable=("entry", "ltm")) -> list:
        """Guidelines always served whatever the router does: gates / rules / sections / reminder / soul /
        code blocks, plus lessons unless lessons are routable."""
        kinds = set(PINNED_TYPES) | ({"lesson"} if "lesson" not in set(routable) else set())
        return [i for i, t in self.node_types.items() if t in kinds and (self.node_texts.get(i) or "").strip()]

    @property
    def week(self) -> str:
        y, w, _ = self.decided_at.isocalendar()
        return f"{y}-W{w:02d}"


def _dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _json(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _tickers_of(value) -> list:
    out = []
    for x in _json(value, []) or []:
        if isinstance(x, dict):
            t = x.get("ticker") or x.get("symbol")
        else:
            t = x
        t = str(t or "").upper().strip()
        if t and t not in out:
            out.append(t)
    return out


def _sessions_before(at: datetime, sessions: int = 2) -> datetime:
    day = at.date()
    left = int(sessions)
    while left > 0:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return datetime.combine(day, datetime.min.time())


def _tables(engine) -> set:
    try:
        return set(inspect(engine).get_table_names())
    except Exception:      # noqa: BLE001
        return set()


def _by_run(engine, sql: str, params: dict, run_ids: list) -> dict:
    out: dict = {}
    if not run_ids:
        return out
    stmt = text(sql).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        for i in range(0, len(run_ids), 500):
            for r in conn.execute(stmt, dict(params, ids=run_ids[i:i + 500])).fetchall():
                out.setdefault(r[0], []).append(r)
    return out


def decider_inputs_for(engine, run_ids: list, tables: Optional[set] = None, *, config_hash: Optional[str] = None) -> dict:
    """{run_id: {field: value}} from a `decider_inputs` table when one exists (any column layout: direct
    columns named like DECIDER_INPUT_KEYS, or a JSON column holding them). Empty otherwise.

    Only the decision call's rows are read when the table has a `call_kind` column: a cycle also logs a
    'citation_repair' row under the same run_id, with no context. Rows are merged oldest first, field by
    field, so a later row never erases what an earlier one recorded."""
    tables = _tables(engine) if tables is None else tables
    if "decider_inputs" not in tables or not run_ids:
        return {}
    try:
        cols = [c["name"] for c in inspect(engine).get_columns("decider_inputs")]
    except Exception:      # noqa: BLE001
        return {}
    if "run_id" not in cols:
        return {}
    sql, params = "SELECT * FROM decider_inputs WHERE run_id IN :ids", {"ids": list(run_ids)}
    if "call_kind" in cols:
        sql += " AND COALESCE(call_kind, 'decide') = 'decide'"
    if config_hash is not None and "config_hash" in cols:
        sql += " AND config_hash = :h"
        params["h"] = config_hash
    if "id" in cols:
        sql += " ORDER BY id"
    stmt = text(sql).bindparams(bindparam("ids", expanding=True))
    out: dict = {}
    with engine.connect() as conn:
        rows = conn.execute(stmt, params).fetchall()
    for r in rows:
        m = dict(r._mapping)
        found: dict = {}
        blobs = [m]
        for k, v in m.items():                       # JSON columns (context / inputs / payload …)
            if isinstance(v, (dict, str)) and k not in ("run_id",):
                j = _json(v, None)
                if isinstance(j, dict):
                    blobs.append(j)
        for b in blobs:
            for field, names in DECIDER_INPUT_KEYS.items():
                if field in found:
                    continue
                for nm in names:
                    if nm in b and b[nm] not in (None, ""):
                        found[field] = b[nm]
                        break
        cur = out.setdefault(str(m["run_id"]), {})
        for f, v in found.items():
            cur.setdefault(f, v)                     # merge: an empty or later row never erases a filled one
    return out


def load_cycles(engine, config_hash: str, *, store_root: Path, agent_type: str = "DeciderAgent",
                kinds=("entry", "lesson", "ltm"), limit: Optional[int] = None, log: Callable = print) -> list:
    """CycleRecords, oldest first. `store_root` = agents/decider/policy-graph/<config_hash>."""
    from policy_graph.compile import read_version_dir

    tables = _tables(engine)
    with engine.connect() as conn:
        runs = conn.execute(text("""
            SELECT run_id, decided_at, prompt_version, context FROM policy_graph_runs
            WHERE config_hash = :h AND agent_type = :a AND run_id IS NOT NULL
            ORDER BY decided_at, id
        """), {"h": config_hash, "a": agent_type}).fetchall()
        hits = conn.execute(text("""
            SELECT run_id, node_id, route, served, cited FROM policy_graph_hits
            WHERE config_hash = :h AND agent_type = :a
        """), {"h": config_hash, "a": agent_type}).fetchall()
    seen, ordered = set(), []
    for r in runs:
        if r[0] in seen or r[2] is None:
            continue
        seen.add(r[0])
        ordered.append(r)
    if limit:
        ordered = ordered[-int(limit):]
    run_ids = [r[0] for r in ordered]
    hits_by: dict = {}
    for h in hits:
        hits_by.setdefault(h[0], []).append(h)
    decisions = _by_run(engine, "SELECT run_id, timestamp, data FROM trade_decisions WHERE config_hash = :h AND run_id IN :ids",
                        {"h": config_hash}, run_ids)
    summaries = _by_run(engine, "SELECT run_id, timestamp, data FROM summaries WHERE run_id IN :ids", {}, run_ids)
    momentum = (_by_run(engine, "SELECT run_id, companies_json, momentum_data FROM momentum_snapshots "
                                "WHERE config_hash = :h AND run_id IN :ids", {"h": config_hash}, run_ids)
                if "momentum_snapshots" in tables else {})
    events = (_by_run(engine, "SELECT run_id, holdings_earnings, watchlist_earnings, block, regime FROM event_risk_snapshots "
                              "WHERE config_hash = :h AND run_id IN :ids", {"h": config_hash}, run_ids)
              if "event_risk_snapshots" in tables else {})
    exits = []
    if "trade_outcomes" in tables:
        with engine.connect() as conn:
            exits = [(str(r[0]).upper(), _dt(r[1])) for r in conn.execute(text(
                "SELECT ticker, sell_timestamp FROM trade_outcomes WHERE config_hash = :h AND sell_timestamp IS NOT NULL"),
                {"h": config_hash}).fetchall() if r[0] and str(r[0]) != "N/A"]
    exact = decider_inputs_for(engine, run_ids, tables, config_hash=config_hash)

    versions: dict = {}
    out = []
    for run_id, decided_at, pv, ctx_json in ordered:
        at = _dt(decided_at)
        pv = int(pv)
        if pv not in versions:
            vdir = Path(store_root) / f"v{pv}"
            try:
                versions[pv] = read_version_dir(vdir)
            except Exception as exc:     # noqa: BLE001
                versions[pv] = None
                log(f"⚠️  policy version v{pv} unreadable ({exc}); its cycles are skipped")
        version = versions[pv]
        if version is None or at is None:
            continue
        nodes = version_nodes(version, kinds)
        node_ids = {n.node_id for n in nodes}
        fires = (version.manifest.get("code") or {}).get("fires") or {}
        parsed = parse_decisions([r[2] for r in decisions.get(run_id, [])])
        source: dict = {}
        ex = exact.get(run_id) or {}
        # ---- context
        regime = str(ex.get("regime") or (_json(ctx_json, {}) or {}).get("regime") or "")
        ev = (events.get(run_id) or [None])[0]
        if not regime and ev is not None and ev[4]:
            regime = str(ev[4])
        if ex.get("holdings") is not None:
            holdings, source["holdings"] = _tickers_of(ex["holdings"]), "decider_inputs"
        elif ev is not None:
            holdings, source["holdings"] = _tickers_of(ev[1]), "event_snapshot"
        else:
            holdings, source["holdings"] = sorted(parsed["holdings"]), "decisions"
        if ex.get("watchlist") is not None:
            watchlist, source["watchlist"] = _tickers_of(ex["watchlist"]), "decider_inputs"
        elif ev is not None:
            watchlist, source["watchlist"] = _tickers_of(ev[2]), "event_snapshot"
        else:
            watchlist, source["watchlist"] = [], "unknown"
        if ex.get("quarantined") is not None:
            quarantined, source["quarantined"] = _tickers_of(ex["quarantined"]), "decider_inputs"
        else:
            cutoff = _sessions_before(at)
            quarantined = sorted({t for t, ts in exits if ts is not None and cutoff <= ts < at})
            source["quarantined"] = "trade_outcomes"
        if ex.get("summaries") is not None:
            raw = _json(ex["summaries"], [])
            summ = [s for s in ((x if isinstance(x, dict) and "headlines" in x else parse_summary_row(x)) for x in raw) if s]
            source["summaries"] = "decider_inputs"
        else:
            rows = sorted(summaries.get(run_id, []), key=lambda r: (_dt(r[1]) or at))[-10:]
            summ = [s for s in (parse_summary_row(r[2]) for r in rows) if s]
            source["summaries"] = "summaries"
        summ.sort(key=lambda s: (s.get("agent") or "").lower())
        news = _tickers_of(ex["news"]) if ex.get("news") is not None else tickers_in_summaries(summ)
        mo = (momentum.get(run_id) or [None])[0]
        entities = (_tickers_of(ex["entities"]) if ex.get("entities") is not None
                    else (_tickers_of(mo[1]) if mo is not None else []))
        trend = (_tickers_of(ex["trend"]) if ex.get("trend") is not None
                 else (_tickers_of(mo[2]) if mo is not None else []))
        if ex.get("event_block"):
            event_block, source["event_block"] = str(ex["event_block"]), "decider_inputs"
        elif ev is not None and ev[3]:
            event_block, source["event_block"] = str(ev[3]), "event_snapshot"
        else:
            event_block, source["event_block"] = "", "none"
        ctx = CycleContext(run_id=run_id, regime=regime, holdings=holdings, watchlist=watchlist,
                           quarantined=quarantined, news=news, entities=entities, trend=trend, summaries=summ,
                           event_block=event_block, today=at)
        # ---- what today's prompt served, and what the decisions cited
        today_ids, ltm_logged = set(), False
        cited = set(parsed["cited"])
        for _r, nid, route, served, was_cited in hits_by.get(run_id, []):
            if served and nid in node_ids:
                today_ids.add(nid)
            if route == "ltm":
                ltm_logged = True
            if was_cited:
                cited.add(nid)
        if not ltm_logged:
            for rid in ((version.manifest.get("ltm") or {}).get("injected_ids") or []):
                if f"DA.ltm.{rid}" in node_ids:
                    today_ids.add(f"DA.ltm.{rid}")
            source["ltm_today"] = "manifest"
        else:
            source["ltm_today"] = "hits"
        if parsed["considered_cites"]:
            source["considered_cites"] = parsed["considered_cites"]
        out.append(CycleRecord(
            run_id=run_id, decided_at=at, prompt_version=pv, ctx=ctx, reasons=parsed["reasons"], pairs=parsed["pairs"],
            cited=cited, decided_tickers=set(parsed["tickers"]), nodes=nodes, today_ids=today_ids,
            node_texts={i: (n.body or "").strip() for i, n in version.nodes.items() if (n.body or "").strip()},
            node_types={i: n.node_type for i, n in version.nodes.items()
                        if (n.body or "").strip() and fires.get(i, True) is not False}, source=source))
    return out


__all__ = ["CycleRecord", "load_cycles", "decider_inputs_for", "DECIDER_INPUT_KEYS", "PINNED_TYPES"]
