"""Prospective candidate ledger and fixed-horizon *paper* outcomes.

Snapshots are written before the Decider call and never rewritten from hindsight.
Model actions are observations, not orders or fills. The denominator is explicitly
the screener candidates supplied to the Decider, not all investable securities.
No config import, credentials, trading client, or model API is used here.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

ET = ZoneInfo("America/New_York")
HORIZONS = (1, 3, 5)
SPEC_ID = "next_session_open_1_3_5_close_v1"
CALENDAR_ID = "nyse_full_day_2026_2027_v1"
SIDE_COST_BPS = 10.0  # explicit fee + slippage assumption, each side
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
FEATURE_KEYS = ("setup", "score", "rsi", "price", "sma20", "dist_sma", "extension_pct", "day_change_pct",
                "change_pct", "r5", "rs5_vs_spy", "rs20_vs_spy", "rel_volume", "ext_tag", "regime",
                "day", "week", "month", "dist_from_20d_ma", "pullback_from_20d_high", "kill_3pct")

DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS learning_opportunities (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    run_id TEXT NOT NULL,
    input_id INTEGER,
    prompt_version INTEGER,
    ticker TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    session_date TEXT NOT NULL,
    coverage TEXT NOT NULL,
    eligible_for_recall BOOLEAN NOT NULL DEFAULT FALSE,
    reference_price DOUBLE PRECISION,
    reference_observed_at TEXT,
    reference_asof TEXT,
    reference_source TEXT,
    spread_bps DOUBLE PRECISION,
    tradable BOOLEAN,
    features_json TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'NOT_ASSESSED',
    reason TEXT,
    cited_json TEXT NOT NULL DEFAULT '[]',
    action_recorded_at TEXT,
    spec_id TEXT NOT NULL,
    side_cost_bps DOUBLE PRECISION NOT NULL,
    UNIQUE(config_hash, run_id, ticker)
)
"""
DDL_OUTCOMES_POSTGRES = """
CREATE TABLE IF NOT EXISTS learning_opportunity_outcomes (
    opportunity_id INTEGER NOT NULL,
    horizon INTEGER NOT NULL,
    status TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    PRIMARY KEY(opportunity_id, horizon)
)
"""
DDL_ATTEMPTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS learning_opportunity_attempts (
    opportunity_id INTEGER PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    last_attempt_at TEXT NOT NULL,
    retry_after_at TEXT NOT NULL,
    status TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
DDL_OUTCOMES_SQLITE = DDL_OUTCOMES_POSTGRES
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_learning_opportunities_config_time ON learning_opportunities(config_hash, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_learning_opportunities_input ON learning_opportunities(config_hash, input_id)",
    "CREATE INDEX IF NOT EXISTS ix_learning_opportunity_attempts_config ON learning_opportunity_attempts(config_hash, last_attempt_at)",
)


def ensure_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(DDL_POSTGRES if engine.dialect.name == "postgresql" else DDL_SQLITE))
        conn.execute(text(DDL_OUTCOMES_POSTGRES))
        conn.execute(text(DDL_ATTEMPTS_POSTGRES))
        for ddl in INDEXES:
            conn.execute(text(ddl))


def _now(value=None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("expected datetime or ISO timestamp")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _positive(value):
    n = _number(value)
    return n if n is not None and n > 0 else None


def _ticker(value):
    t = str(value or "").strip().upper()
    return t if TICKER_RE.fullmatch(t) and t not in {"CASH", "PORTFOLIO", "NONE", "UNKNOWN"} else None


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _features(candidate, regime=None):
    out = {}
    for key in FEATURE_KEYS:
        value = candidate.get(key)
        if isinstance(value, str):
            out[key] = value[:250]
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and _number(value) is not None:
            out[key] = value
    if regime:
        out["regime"] = str(regime)[:40]
    return out


def record_snapshot(engine, config_hash, run_id, candidates, *, input_id=None, prompt_version=None,
                    context=None, observed_at=None, holdings=(), quarantined=()) -> int:
    """Persist pre-call screener candidates and known context tickers, with no quote/API calls.

    A supplied price is only a reference observed at this snapshot. Its market
    timestamp stays unknown unless explicitly supplied; it never prices paper entry.
    Repeated writes for a run/ticker preserve the first immutable snapshot.
    """
    if not config_hash or not run_id:
        return 0
    ensure_schema(engine)
    now = _now(observed_at)
    held = {_ticker(x.get("ticker") if isinstance(x, dict) else x) for x in holdings}
    blocked = {_ticker(x) for x in quarantined}
    records = {}
    for raw in candidates or ():
        c = raw if isinstance(raw, dict) else {"ticker": raw}
        ticker = _ticker(c.get("ticker"))
        if ticker:
            records[ticker] = (c, "prospective_screener", ticker not in held and ticker not in blocked and c.get("tradable") is not False)
    ctx = context if isinstance(context, dict) else {}
    for field in ("holdings", "watchlist", "quarantined", "news", "entities", "trend"):
        for raw in ctx.get(field) or ():
            ticker = _ticker(raw)
            if ticker and ticker not in records:
                records[ticker] = ({"ticker": ticker}, "prospective_context", False)
    inserted = 0
    with engine.begin() as conn:
        for ticker, (c, coverage, eligible) in records.items():
            price = _positive(c.get("price"))
            asof = c.get("price_asof")
            if asof:
                try:
                    asof_dt = _now(asof)
                    if asof_dt > now:
                        price = None
                        c = {k:v for k,v in c.items() if k != "price"}
                        asof = None
                    else:
                        asof = asof_dt.isoformat()
                except (ValueError, TypeError):
                    asof = None
            spread = _number(c.get("spread_bps"))
            if spread is not None and spread < 0:
                spread = None
            tradable = c.get("tradable") if isinstance(c.get("tradable"), bool) else None
            params = {"h": str(config_hash), "r": str(run_id), "i": input_id, "v": prompt_version,
                      "ticker": ticker, "t": now.isoformat(), "d": now.astimezone(ET).date().isoformat(),
                      "coverage": coverage, "eligible": eligible, "p": price,
                      "po": now.isoformat() if price is not None else None, "pa": asof,
                      "source": "screener_snapshot" if price is not None else "unavailable",
                      "spread": spread, "tradable": tradable, "f": _json(_features(c, ctx.get("regime"))),
                      "spec": SPEC_ID, "cost": SIDE_COST_BPS}
            result = conn.execute(text("""
                INSERT INTO learning_opportunities
                (config_hash,run_id,input_id,prompt_version,ticker,observed_at,session_date,coverage,
                 eligible_for_recall,reference_price,reference_observed_at,reference_asof,reference_source,
                 spread_bps,tradable,features_json,spec_id,side_cost_bps)
                VALUES (:h,:r,:i,:v,:ticker,:t,:d,:coverage,:eligible,:p,:po,:pa,:source,:spread,:tradable,:f,:spec,:cost)
                ON CONFLICT(config_hash,run_id,ticker) DO NOTHING
            """), params)
            inserted += max(0, result.rowcount)
    return inserted


def _reply_items(reply):
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except (ValueError, TypeError):
            return []
    if isinstance(reply, dict):
        considered = reply.get("considered") if isinstance(reply.get("considered"), list) else []
        decisions = reply.get("decisions") if isinstance(reply.get("decisions"), list) else [reply]
    elif isinstance(reply, list):
        considered, decisions = [], reply
    else:
        return []
    out = {}
    mapping = {"BUY": "BUY", "SELL": "SELL", "HOLD": "HOLD", "PASS": "PASS", "REJECT": "PASS",
               "REJECTED": "PASS", "SKIP": "PASS", "NO BUY": "PASS", "NO_BUY": "PASS"}
    # Explicit decisions win over a conflicting considered/setup verdict.
    for item in list(considered) + list(decisions):
        if not isinstance(item, dict):
            continue
        ticker = _ticker(item.get("ticker"))
        if not ticker:
            continue
        action = mapping.get(str(item.get("action") or item.get("verdict") or "").strip().upper(), "NOT_ASSESSED")
        cites = item.get("cited") or []
        if not isinstance(cites, list):
            cites = []
        out[ticker] = {"ticker": ticker, "action": action,
                       "reason": str(item.get("reason") or item.get("why") or "")[:4000],
                       "cited": [str(c)[:160] for c in cites if isinstance(c, str)][:40]}
    return list(out.values())


def record_decisions(engine, config_hash, run_id, reply, *, input_id=None, prompt_version=None,
                     recorded_at=None) -> int:
    """Attach the model's first observed action. New response-only names cannot enter recall."""
    if not config_hash or not run_id:
        return 0
    ensure_schema(engine)
    now = _now(recorded_at)
    count = 0
    with engine.begin() as conn:
        for item in _reply_items(reply):
            conn.execute(text("""
                INSERT INTO learning_opportunities
                (config_hash,run_id,input_id,prompt_version,ticker,observed_at,session_date,coverage,
                 eligible_for_recall,features_json,spec_id,side_cost_bps)
                VALUES (:h,:r,:i,:v,:ticker,:t,:d,'postdecision',FALSE,'{}',:spec,:cost)
                ON CONFLICT(config_hash,run_id,ticker) DO NOTHING
            """), {"h": config_hash, "r": str(run_id), "i": input_id, "v": prompt_version,
                     "ticker": item["ticker"], "t": now.isoformat(), "d": now.astimezone(ET).date().isoformat(),
                     "spec": SPEC_ID, "cost": SIDE_COST_BPS})
            result = conn.execute(text("""
                UPDATE learning_opportunities SET action=:a,reason=:reason,cited_json=:c,action_recorded_at=:t
                WHERE config_hash=:h AND run_id=:r AND ticker=:ticker AND action_recorded_at IS NULL
            """), {"a": item["action"], "reason": item["reason"], "c": _json(item["cited"]),
                     "t": now.isoformat(), "h": config_hash, "r": str(run_id), "ticker": item["ticker"]})
            count += max(0, result.rowcount)
    return count


def _dates(case, horizon):
    """Expected calendar dates, never inferred by shifting across missing ticker bars."""
    from event_calendar import NYSE_HOLIDAYS
    observed = _now(case["observed_at"]).astimezone(ET).date()
    holidays = {date.fromisoformat(d) for values in NYSE_HOLIDAYS.values() for d in values}
    dates = []
    cursor = observed
    for _ in range(40):
        cursor += timedelta(days=1)
        if cursor.year not in NYSE_HOLIDAYS:
            return None
        if cursor.weekday() < 5 and cursor not in holidays:
            dates.append(cursor)
            if len(dates) >= horizon:
                return dates
    return None


def evaluate_case(case, bars, *, now=None, horizons=HORIZONS) -> dict:
    """Pure adjusted-OHLC next-session-open paper marking for 1/3/5 sessions.

    `bars` is a list of {date,open,high,low,close,adjusted:true}. Unknown adjustment,
    incomplete data, future daily bars, or unknown holiday coverage never mature.
    Exit is only available after 17:00 ET, conservatively after all regular/short closes.
    """
    now = _now(now)
    by_date = {}
    for bar in bars or ():
        if not isinstance(bar, dict):
            continue
        try:
            d = date.fromisoformat(str(bar.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        by_date[d] = bar
    out = {}
    for horizon in horizons:
        if horizon not in HORIZONS:
            raise ValueError("unsupported paper horizon")
        dates = _dates(case, horizon)
        result = {"horizon": horizon, "status": "pending", "spec_id": case.get("spec_id", SPEC_ID),
                  "calendar_id": CALENDAR_ID, "side_cost_bps": case.get("side_cost_bps", SIDE_COST_BPS),
                  "source": "adjusted_daily_ohlc", "execution": "paper_next_session_open_to_horizon_close",
                  "entry_date": dates[0].isoformat() if dates else None,
                  "exit_date": dates[-1].isoformat() if dates else None,
                  "entry_price": None, "exit_price": None, "net_return_pct": None,
                  "gross_return_pct": None, "net_pnl_per_1000": None,
                  "mae_pct": None, "mfe_pct": None, "label": None}
        if dates is None:
            result["status"] = "calendar_unknown"
        elif now < datetime.combine(dates[-1], time(17), tzinfo=ET).astimezone(timezone.utc):
            pass
        else:
            window = [by_date.get(d) for d in dates]
            if not all(b and b.get("adjusted") is True and all(_positive(b.get(k)) is not None for k in ("open", "high", "low", "close")) for b in window):
                result["status"] = "missing_data"
            elif not all(_positive(b["low"]) <= min(_positive(b["open"]), _positive(b["close"])) <= max(_positive(b["open"]), _positive(b["close"])) <= _positive(b["high"]) for b in window):
                result["status"] = "missing_data"
            else:
                entry, exit_ = float(window[0]["open"]), float(window[-1]["close"])
                side = _number(case.get("side_cost_bps", SIDE_COST_BPS))
                if side is None or side < 0 or side >= 10000:
                    raise ValueError("invalid paper cost assumption")
                cost = side / 10000.0
                gross = exit_ / entry - 1
                net = exit_ * (1 - cost) / (entry * (1 + cost)) - 1
                result.update(status="matured", entry_price=entry, exit_price=exit_,
                              gross_return_pct=round(gross*100, 8), net_return_pct=round(net*100, 8),
                              net_pnl_per_1000=round(net*1000, 8),
                              mae_pct=round((min(float(b["low"]) for b in window)/entry-1)*100, 8),
                              mfe_pct=round((max(float(b["high"]) for b in window)/entry-1)*100, 8),
                              label="winner" if net > 1e-10 else "loser" if net < -1e-10 else "break_even")
        out[str(horizon)] = result
    return out


def list_cases(engine, config_hash, *, days=90, limit=500, oldest_first=False, pending_only=False) -> list:
    ensure_schema(engine)
    days = max(1, min(3650, int(days)))
    limit = max(1, min(5000, int(limit)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    order = "ASC" if oldest_first else "DESC"
    pending_sql = (" AND (SELECT COUNT(*) FROM learning_opportunity_outcomes o WHERE "
                   "o.opportunity_id=learning_opportunities.id AND o.status='matured') < 3") if pending_only else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""SELECT * FROM learning_opportunities WHERE config_hash=:h
            AND observed_at >= :cutoff {pending_sql} ORDER BY observed_at {order},id {order} LIMIT :lim"""),
            {"h": config_hash, "cutoff": cutoff, "lim": limit}).mappings().all()
        ids = [int(r["id"]) for r in rows]
        outcomes = _load_outcomes(conn, ids)
    return _decode_case_rows(rows,outcomes)


def _decode_case_rows(rows,outcomes):
    out = []
    for row in rows:
        item = dict(row)
        for column, destination, fallback in (("features_json", "features", {}), ("cited_json", "cited", [])):
            try:
                item[destination] = json.loads(item.pop(column))
            except (TypeError, ValueError):
                item[destination] = fallback
        item["eligible_for_recall"] = bool(item["eligible_for_recall"])
        item["tradable"] = None if item["tradable"] is None else bool(item["tradable"])
        item["outcomes"] = outcomes.get(item["id"], {})
        out.append(item)
    return out


def _load_outcomes(conn, ids):
    outcomes = {}
    for offset in range(0, len(ids), 400):
        chunk = ids[offset:offset+400]
        params = {f"i{i}": v for i,v in enumerate(chunk)}
        placeholders = ",".join(":"+k for k in params)
        for r in conn.execute(text(f"SELECT opportunity_id,horizon,outcome_json FROM learning_opportunity_outcomes WHERE opportunity_id IN ({placeholders})"), params).mappings():
            try:
                outcomes.setdefault(int(r["opportunity_id"]), {})[str(r["horizon"])] = json.loads(r["outcome_json"])
            except (ValueError, TypeError):
                pass
    return outcomes


MAX_REPORT_COHORT = 50000


def report(engine, config_hash, *, days=90, case_limit=500):
    """Separate bounded display rows from quality's complete declared cohort.

    Context-only/postdecision rows cannot push an earlier prospective PASS out
    of quality denominators. Above the bounded 50k-candidate limit all quality
    rates are suppressed, rather than reported on a convenient partial sample.
    """
    ensure_schema(engine)
    days = max(1, min(3650, int(days)))
    case_limit = max(1,min(5000,int(case_limit)))
    now = datetime.now(timezone.utc)
    cutoff = (now-timedelta(days=days)).isoformat()
    params = {"h": config_hash, "t": cutoff}
    base = "FROM learning_opportunities WHERE config_hash=:h AND observed_at>=:t"
    eligible = " AND coverage='prospective_screener' AND eligible_for_recall=TRUE"
    with engine.connect() as conn:
        total = int(conn.execute(text("SELECT COUNT(*) "+base),params).scalar_one())
        cohort_total = int(conn.execute(text("SELECT COUNT(*) "+base+eligible),params).scalar_one())
        cohort = []
        if cohort_total <= MAX_REPORT_COHORT:
            rows=conn.execute(text("SELECT id,ticker,observed_at,coverage,eligible_for_recall,action,spec_id "+base+eligible+
                                   " ORDER BY observed_at ASC,id ASC LIMIT :lim"),
                              {**params,"lim":MAX_REPORT_COHORT+1}).mappings().all()
            cohort=[dict(r) for r in rows]
            cohort_total=max(cohort_total,len(cohort))
            if len(cohort)<=MAX_REPORT_COHORT:
                outcomes=_load_outcomes(conn,[c["id"] for c in cohort])
                for c in cohort:
                    c["eligible_for_recall"]=bool(c["eligible_for_recall"])
                    c["outcomes"]=outcomes.get(c["id"],{})
    truncated=cohort_total>MAX_REPORT_COHORT
    displayed=list_cases(engine,config_hash,days=days,limit=case_limit)
    by_horizon={}
    for horizon in HORIZONS:
        summary=metrics(cohort if not truncated else [],horizon=horizon)
        summary.update(window_days=days,cohort_rows=cohort_total,cohort_truncated=truncated)
        if truncated:
            for key in ("prospective_candidates","episodes","deduplicated","assessed","unassessed",
                        "matured","unmatured","tp","fp","fn","tn","winner_denominator","loser_denominator",
                        "buy_denominator","break_even"):
                summary[key]=None
            summary["candidate_rows"]=cohort_total
            summary["note"]="Quality rates unavailable: the declared prospective cohort exceeds the 50,000-candidate report limit. No partial-sample rates are shown."
        by_horizon[str(horizon)]=summary
    note=(f"Showing {len(displayed):,} of {total:,} recorded rows from the last {days} days. "
          + (f"Quality rates are unavailable because the prospective screener cohort has {cohort_total:,} rows, above the 50,000-row report limit."
             if truncated else f"Quality metrics use all {cohort_total:,} prospective eligible supplied screener candidates in this window, before non-overlapping episode deduplication; map display limits do not change the denominator."))
    return {"cases":displayed,"metrics":by_horizon["3"],"metrics_by_horizon":by_horizon,
            "coverage_note":note,"window_days":days,"total_rows":total,"displayed_rows":len(displayed),
            "cohort_rows":cohort_total,"cohort_truncated":truncated,"generated_at":now.isoformat()}


def _ratio(n, d):
    return n / d if d else None


def has_pending(engine, config_hash, *, days=120) -> bool:
    """Cheap maintenance preflight. No quotes or models are queried."""
    if not config_hash:
        return False
    ensure_schema(engine)
    cutoff = (datetime.now(timezone.utc)-timedelta(days=max(1,min(3650,int(days))))).isoformat()
    with engine.connect() as conn:
        return conn.execute(text("""SELECT 1 FROM learning_opportunities c
            WHERE c.config_hash=:h AND c.observed_at>=:t AND
            (SELECT COUNT(*) FROM learning_opportunity_outcomes o
             WHERE o.opportunity_id=c.id AND o.status='matured') < 3 LIMIT 1"""),
            {"h":config_hash,"t":cutoff}).fetchone() is not None


def _interval(n, d):
    if not d:
        return None
    z = 1.96
    p = n / d
    center = (p + z*z/(2*d))/(1+z*z/d)
    half = z*math.sqrt(p*(1-p)/d + z*z/(4*d*d))/(1+z*z/d)
    return [max(0, center-half), min(1, center+half)]


def metrics(cases, *, horizon=3) -> dict:
    if horizon not in HORIZONS:
        raise ValueError("unsupported paper horizon")
    prospective = [c for c in cases if c.get("coverage") == "prospective_screener" and c.get("eligible_for_recall")]
    candidates = sorted(prospective, key=lambda c: (str(c.get("observed_at", "")), int(c.get("id") or 0)))
    # First candidate per ticker's non-overlapping paper episode. A later decision
    # cannot replace an earlier miss merely because the later observation won.
    last_exit, episodes = {}, []
    for c in candidates:
        dates = _dates(c, horizon)
        if dates is None:
            episodes.append(c)
            continue
        ticker = c.get("ticker")
        if ticker in last_exit and dates[0] <= last_exit[ticker]:
            continue
        last_exit[ticker] = dates[-1]
        episodes.append(c)
    assessed = [c for c in episodes if c.get("action") in {"BUY", "PASS"}]
    mature = [(c, c.get("outcomes", {}).get(str(horizon), {})) for c in assessed]
    mature = [(c,o) for c,o in mature if o.get("status") == "matured"
              and o.get("label") in {"winner", "loser", "break_even"}
              and _number(o.get("net_return_pct")) is not None]
    tp = sum(c["action"] == "BUY" and o["label"] == "winner" for c,o in mature)
    fp = sum(c["action"] == "BUY" and o["label"] == "loser" for c,o in mature)
    fn = sum(c["action"] == "PASS" and o["label"] == "winner" for c,o in mature)
    tn = sum(c["action"] == "PASS" and o["label"] == "loser" for c,o in mature)
    buys = [o for c,o in mature if c["action"] == "BUY"]
    net = [_number(o.get("net_return_pct")) for o in buys]
    net = [n for n in net if n is not None]
    return {"horizon": horizon, "spec_id": SPEC_ID, "scope": "prospective screener candidates, first non-overlapping ticker episode",
            "paper_only": True, "candidate_rows": len(cases), "prospective_candidates": len(prospective),
            "episodes": len(episodes), "deduplicated": len(prospective)-len(episodes),
            "assessed": len(assessed), "unassessed": len(episodes)-len(assessed),
            "matured": len(mature), "unmatured": len(assessed)-len(mature),
            "coverage": _ratio(len(assessed), len(episodes)), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "winner_denominator": tp+fn, "loser_denominator": fp+tn, "buy_denominator": tp+fp,
            "precision": _ratio(tp,tp+fp), "recall": _ratio(tp,tp+fn), "fpr": _ratio(fp,fp+tn),
            "precision_interval": _interval(tp,tp+fp), "recall_interval": _interval(tp,tp+fn), "fpr_interval": _interval(fp,fp+tn),
            "break_even": sum(o["label"] == "break_even" for _,o in mature),
            "net_expectancy_pct": sum(net)/len(net) if net else None,
            "net_pnl_per_1000": sum(net)*10 if net else None,
            "note": "Model BUY/PASS only; paper returns assume 10 bps each side. Not realized portfolio P&L, all-market recall, or causal rule attribution."}


def refresh_outcomes(engine, config_hash, *, loader=None, now=None, limit=300, max_tickers=40) -> dict:
    """Bounded maintenance job, never called by the trading decision path.

    Loader signature (ticker,start_date,end_date)->adjusted OHLC dictionaries.
    The default yfinance source is retrospective adjusted daily data, not fills.
    Completed outcomes are frozen; absent/delisted bars remain explicitly missing.
    Queue order is never-attempted then least-recently-attempted, before either
    bound. Failed/missing data gets a retry delay, so old unavailable rows cannot
    permanently hide a later healthy case (including another case of one ticker).
    """
    now = _now(now)
    ensure_schema(engine)
    limit=max(1,min(5000,int(limit)))
    # Apply fairness and backoff in SQL, before the row and unique-ticker caps.
    with engine.connect() as conn:
        rows=conn.execute(text("""SELECT c.*,a.last_attempt_at,a.failures AS attempt_failures
            FROM learning_opportunities c LEFT JOIN learning_opportunity_attempts a
              ON a.opportunity_id=c.id AND a.config_hash=c.config_hash
            WHERE c.config_hash=:h AND c.observed_at>=:cutoff
              AND (SELECT COUNT(*) FROM learning_opportunity_outcomes o
                   WHERE o.opportunity_id=c.id AND o.status='matured') < 3
              AND (a.retry_after_at IS NULL OR a.retry_after_at<=:now)
            ORDER BY CASE WHEN a.last_attempt_at IS NULL THEN 0 ELSE 1 END,
                     a.last_attempt_at ASC,c.observed_at ASC,c.id ASC LIMIT :lim"""),
            {"h":config_hash,"cutoff":(now-timedelta(days=120)).isoformat(),"now":now.isoformat(),"lim":limit}).mappings().all()
        outcomes=_load_outcomes(conn,[r["id"] for r in rows])
    pending=_decode_case_rows(rows,outcomes)
    selected = []
    for c in pending:
        if c["ticker"] not in selected:
            selected.append(c["ticker"])
        if len(selected) >= max(1,min(100,int(max_tickers))):
            break
    if loader is None:
        def loader(ticker, start, end):
            import yfinance as yf
            frame = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                             interval="1d", auto_adjust=True, actions=False, timeout=8)
            return [{"date": idx.date().isoformat(), "open": row["Open"], "high": row["High"],
                     "low": row["Low"], "close": row["Close"], "adjusted": True} for idx,row in frame.iterrows()]
    written, failures = 0, 0
    for ticker in selected:
        group = [c for c in pending if c["ticker"] == ticker]
        start = min(_now(c["observed_at"]).astimezone(ET).date() for c in group)
        # Stamp before I/O, including failed requests or interrupted workers.
        with engine.begin() as conn:
            for c in group:
                _record_attempt(conn,config_hash,c,now,"attempting",timedelta(minutes=5),int(c.get("attempt_failures") or 0))
        try:
            bars = loader(ticker, start, now.astimezone(ET).date()+timedelta(days=1))
        except Exception:
            failures += 1
            with engine.begin() as conn:
                for c in group:
                    previous=int(c.get("attempt_failures") or 0)
                    delay=timedelta(hours=min(24,2**min(previous,5)))
                    _record_attempt(conn,config_hash,c,now,"source_error",delay,previous+1)
            continue
        with engine.begin() as conn:
            for c in group:
                evaluated=evaluate_case(c,bars,now=now)
                for horizon,result in evaluated.items():
                    if c.get("outcomes",{}).get(horizon,{}).get("status") == "matured":
                        continue
                    conn.execute(text("""INSERT INTO learning_opportunity_outcomes
                        (opportunity_id,horizon,status,outcome_json,measured_at) VALUES (:i,:h,:s,:j,:t)
                        ON CONFLICT(opportunity_id,horizon) DO UPDATE SET status=excluded.status,
                        outcome_json=excluded.outcome_json,measured_at=excluded.measured_at
                        WHERE learning_opportunity_outcomes.status <> 'matured'"""),
                        {"i": c["id"], "h": int(horizon), "s": result["status"], "j": _json(result), "t": now.isoformat()})
                    written += 1
                remaining=[evaluated[str(h)]["status"] for h in HORIZONS
                           if c.get("outcomes",{}).get(str(h),{}).get("status") != "matured"]
                status="matured" if all(s=="matured" for s in remaining) else "pending" if "pending" in remaining else "missing_data"
                _record_attempt(conn,config_hash,c,now,status,timedelta(hours=6),0)
    return {"tickers": len(selected), "outcomes_written": written, "source_failures": failures,
            "paper_only": True, "spec_id": SPEC_ID}


def _record_attempt(conn,config_hash,case,now,status,delay,failures):
    conn.execute(text("""INSERT INTO learning_opportunity_attempts
        (opportunity_id,config_hash,last_attempt_at,retry_after_at,status,failures)
        VALUES (:i,:h,:t,:retry,:s,:f)
        ON CONFLICT(opportunity_id) DO UPDATE SET
        config_hash=excluded.config_hash,last_attempt_at=excluded.last_attempt_at,
        retry_after_at=excluded.retry_after_at,status=excluded.status,failures=excluded.failures"""),
        {"i":case["id"],"h":config_hash,"t":now.isoformat(),"retry":(now+delay).isoformat(),"s":status,"f":failures})
