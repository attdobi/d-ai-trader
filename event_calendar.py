"""Scheduled binary events for the Decider: FOMC / CPI / jobs-report calendar, NYSE sessions,
earnings dates of the names in play, one event-risk score, and the EVENT CALENDAR prompt block.

Why (audit 2026-09-14): the Summarizers flagged the Sep 16 FOMC decision in 8 of 36 summaries that
day, in the very paragraph the Decider reads, and 0 of the 96 Decider outputs of the previous 30
days mentioned the Fed, a macro print or an earnings date. Nothing consumed the signal: the regime
gate is purely technical (SPY/QQQ vs 20d MA + leader cohort), the prompt carried no date, and no
holding or candidate carried its earnings date — the MDB −15.2% loss (2026-09-02) was an earnings
gap through a "20d break" kill. This module supplies the missing deterministic inputs the same way
contrarian_screener supplies the INDEX REGIME line: pure Python + yfinance, no LLM cost, best-effort
(any failure degrades to an empty block, never breaks the decision path).

What it produces each cycle (`build_event_context`):
  * TODAY — the session date and ET time (the Decider had no date before this).
  * MACRO — the next FOMC decision (2:00 pm ET, second day of the meeting), CPI and jobs report
    (8:30 am ET) with the number of trading sessions until each, plus what printed recently.
  * EARNINGS — the next earnings date of every holding and watchlist name (yfinance `calendar`,
    cached in memory and in `earnings_calendar`), with the sessions until it.
  * MACRO WINDOW — FOMC within the next 2 sessions (or today before 2 pm ET); CPI / jobs report
    next session. A 1–5 day hold entered inside the window sits through the print.
  * an event-risk SCORE 0–100 (regime base + macro proximity + earnings inside the hold window)
    and the ALLOWANCE the EVENT GATE implies for new BUYs and for holdings that report soon.
The thresholds the score encodes mirror the EVENT GATE guideline in the Decider's policy graph
(DA.directives.strategy.event_gate); the block itself only carries data — the gate decides.

Calendars: FOMC 2026–2027 (federalreserve.gov), CPI and Employment Situation 2026 (bls.gov), NYSE
holidays 2026–2027. `DAI_EVENT_CALENDAR_FILE` may point to a JSON file that adds dates:
{"fomc": [...], "cpi": [...], "jobs": [...], "holidays": [...], "other": [{"date": "...", "label": "..."}]}.

Public API:
    build_event_context(holdings, watchlist, regime=None, now_et=None, lookup_earnings=True, engine=None) -> dict
    format_event_calendar(ctx) -> str                  # prompt-ready block ('' when disabled)
    macro_statuses(today, now_time=None) -> dict       # FOMC / CPI / jobs status for any date
    score_event_risk(regime, statuses, holdings_earnings) -> (score, level, parts)
    ensure_tables(engine) / record_snapshot(engine, config_hash, run_id, ctx) / latest_snapshot(engine, config_hash)
    event_risk_payload(engine, config_hash, days, regime_for, holdings) -> dict   # dashboard series
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- calendars
# FOMC: decision day = second day of each two-day meeting; statement at 2:00 pm ET.
FOMC_DECISION_DATES = {
    2026: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
    2027: ["2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"],
}
# BLS Consumer Price Index, 8:30 am ET.
CPI_RELEASE_DATES = {
    2026: ["2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
           "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10"],
}
# BLS Employment Situation (jobs report), 8:30 am ET.
JOBS_REPORT_DATES = {
    2026: ["2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
           "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"],
}
# NYSE full-day closures.
NYSE_HOLIDAYS = {
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
           "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
           "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"],
}

FOMC_RELEASE_ET = dtime(14, 0)
PRINT_RELEASE_ET = dtime(8, 30)
FOMC_WINDOW_SESSIONS = 2          # a 1–5 day hold entered ≤2 sessions before the decision sits through it
PRINT_WINDOW_SESSIONS = 1         # CPI / jobs: the session before the 8:30 am print
EARNINGS_REJECT_SESSIONS = 5      # candidate reporting inside the hold window → reject
EARNINGS_EXIT_SESSIONS = 2        # holding reporting this soon → sell / trim before the print

# Score weights (0–100, capped). Regime base + macro proximity + earnings inside the hold window.
REGIME_BASE = {"RISK-ON": 10, "MIXED": 30, "RISK-OFF": 55}
FOMC_POINTS = {"window": {0: 35, 1: 30, 2: 20}, "near": {3: 8}, "post": 10}
PRINT_POINTS = {"window": {0: 12, 1: 12}, "near": {2: 4}, "post": 6}
EARNINGS_POINTS = {"exit": 20, "exit_cap": 40, "reject": 8, "reject_cap": 16}
LEVELS = ((25, "LOW"), (50, "ELEVATED"), (75, "HIGH"), (101, "EXTREME"))

_CACHE_FILE = {"path": None, "mtime": None, "data": {}}


def _iso(d) -> Optional[str]:
    return d.isoformat() if isinstance(d, date) else (str(d) if d else None)


def _parse_date(s) -> Optional[date]:
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _extra_calendar() -> dict:
    """Operator additions from DAI_EVENT_CALENDAR_FILE (re-read when the file changes)."""
    path = (os.getenv("DAI_EVENT_CALENDAR_FILE") or "").strip()
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
        if _CACHE_FILE["path"] == path and _CACHE_FILE["mtime"] == mtime:
            return _CACHE_FILE["data"]
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        _CACHE_FILE.update({"path": path, "mtime": mtime, "data": data if isinstance(data, dict) else {}})
        return _CACHE_FILE["data"]
    except Exception as exc:     # noqa: BLE001
        logger.warning("event calendar file %s unreadable: %s", path, exc)
        return {}


def _dates(table: dict, key: str) -> list:
    out = {d for ys in table.values() for d in map(_parse_date, ys) if d}
    out |= {d for d in map(_parse_date, _extra_calendar().get(key) or []) if d}
    return sorted(out)


def fomc_dates() -> list:
    return _dates(FOMC_DECISION_DATES, "fomc")


def cpi_dates() -> list:
    return _dates(CPI_RELEASE_DATES, "cpi")


def jobs_dates() -> list:
    return _dates(JOBS_REPORT_DATES, "jobs")


_HOL_CACHE = {"key": None, "set": frozenset()}


def holidays() -> frozenset:
    """NYSE closures (built-in + operator file), memoized per calendar-file state — sessions_between
    walks day by day, so this is called thousands of times per dashboard payload."""
    _extra_calendar()
    key = (_CACHE_FILE["path"], _CACHE_FILE["mtime"])
    if _HOL_CACHE["key"] != key:
        _HOL_CACHE["set"] = frozenset(_dates(NYSE_HOLIDAYS, "holidays"))
        _HOL_CACHE["key"] = key
    return _HOL_CACHE["set"]


def _params(engine, params: dict) -> dict:
    """SQLite has no DATE/TIMESTAMP types: pass ISO strings there, native dates on Postgres."""
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    if dialect == "postgresql":
        return params
    return {k: (v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v)
            for k, v in params.items()}


def other_events() -> list:
    """[(date, label)] operator-added one-off events (window: the session before)."""
    out = []
    for e in _extra_calendar().get("other") or []:
        if isinstance(e, dict):
            d = _parse_date(e.get("date"))
            if d:
                out.append((d, str(e.get("label") or "event")[:60]))
    return sorted(out)


# ----------------------------------------------------------------------------- sessions
def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays()


def sessions_between(a: date, b: date) -> int:
    """Trading sessions in (a, b]; negative when b is before a; 0 when equal."""
    if a == b:
        return 0
    if b < a:
        return -sessions_between(b, a)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if is_session(d):
            n += 1
    return n


def add_sessions(d: date, n: int) -> date:
    """The date n trading sessions after d (n=0 → d itself)."""
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if is_session(d):
            left -= 1
    return d


def session_state(now_et: datetime) -> str:
    if not is_session(now_et.date()):
        return "weekend/holiday"
    t = now_et.time()
    if t < dtime(9, 30):
        return "pre-market"
    if t <= dtime(16, 0):
        return "session open"
    return "after hours"


# ----------------------------------------------------------------------------- macro status
def _status(kind: str, label: str, dates: list, today: date, now_time: Optional[dtime], release: dtime,
            window: int) -> dict:
    future = [d for d in dates if d >= today]
    past = [d for d in dates if d < today]
    phase = None
    if future and future[0] == today:
        phase = "pre" if (now_time is None or now_time < release) else "post"
        if phase == "post":
            past.append(future.pop(0))
    nxt = future[0] if future else None
    st = sessions_between(today, nxt) if nxt else None
    last = past[-1] if past else None
    since = sessions_between(last, today) if last else None
    in_window = st is not None and ((st == 0 and phase == "pre") or 1 <= st <= window)
    post_span = 1 if kind == "FOMC" else 0
    just_printed = since is not None and since <= post_span
    return {
        "kind": kind, "label": label, "next": _iso(nxt), "sessions_to": st, "phase": phase,
        "release_et": release.strftime("%-I:%M %p").lower() + " ET", "last": _iso(last),
        "sessions_since": since, "in_window": in_window, "just_printed": just_printed,
        "calendar_exhausted": nxt is None,
    }


def macro_statuses(today: date, now_time: Optional[dtime] = None) -> dict:
    """{'fomc': status, 'cpi': status, 'jobs': status, 'other': [status, ...]} for `today`.
    `now_time` (ET) decides pre/post on a release day; None = start of day (pre)."""
    out = {
        "fomc": _status("FOMC", "FOMC decision", fomc_dates(), today, now_time, FOMC_RELEASE_ET, FOMC_WINDOW_SESSIONS),
        "cpi": _status("CPI", "CPI", cpi_dates(), today, now_time, PRINT_RELEASE_ET, PRINT_WINDOW_SESSIONS),
        "jobs": _status("JOBS", "jobs report", jobs_dates(), today, now_time, PRINT_RELEASE_ET, PRINT_WINDOW_SESSIONS),
        "other": [],
    }
    for d, label in other_events():
        if d < today - timedelta(days=3):
            continue
        out["other"].append(_status("OTHER", label, [d], today, now_time, PRINT_RELEASE_ET, PRINT_WINDOW_SESSIONS))
    return out


def macro_window(statuses: dict) -> tuple:
    """(in_window, reason) across FOMC / CPI / jobs / operator events."""
    reasons = []
    for key in ("fomc", "cpi", "jobs"):
        s = statuses.get(key) or {}
        if s.get("in_window"):
            reasons.append(_when(s))
    for s in statuses.get("other") or []:
        if s.get("in_window"):
            reasons.append(_when(s))
    return bool(reasons), "; ".join(reasons)


def _fmt_day(iso: Optional[str]) -> str:
    d = _parse_date(iso)
    return d.strftime("%a %Y-%m-%d") if d else "not_in_calendar"


def _when(s: dict) -> str:
    st = s.get("sessions_to")
    if st is None:
        return f"{s['label']} not_in_calendar"
    if st == 0:
        return f"{s['label']} TODAY {s['release_et']} ({s.get('phase') or 'pre'})"
    return f"{s['label']} {_fmt_day(s['next'])} (in {st} session{'s' if st != 1 else ''})"


# ----------------------------------------------------------------------------- earnings
_EARN_CACHE: dict = {}      # ticker -> {"date": date|None, "estimate": bool, "ts": epoch, "source": str}

DDL_EARNINGS_POSTGRES = """
CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker TEXT PRIMARY KEY,
    next_earnings_date DATE,
    estimate BOOLEAN DEFAULT FALSE,
    fetched_at TIMESTAMP NOT NULL,
    source TEXT
)
"""
DDL_SNAPSHOTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS event_risk_snapshots (
    id SERIAL PRIMARY KEY,
    config_hash TEXT NOT NULL,
    run_id TEXT,
    as_of TIMESTAMP NOT NULL,
    session_date DATE NOT NULL,
    regime TEXT,
    risk_score INTEGER NOT NULL,
    risk_level TEXT,
    macro_window BOOLEAN,
    macro_reason TEXT,
    fomc_date DATE,
    fomc_sessions INTEGER,
    cpi_date DATE,
    cpi_sessions INTEGER,
    jobs_date DATE,
    jobs_sessions INTEGER,
    holdings_earnings TEXT,
    watchlist_earnings TEXT,
    allowance TEXT,
    block TEXT
)
"""
_DDL_INDEX = "CREATE INDEX IF NOT EXISTS ix_event_risk_snapshots_cfg ON event_risk_snapshots (config_hash, session_date)"


def ensure_tables(engine) -> None:
    from sqlalchemy import text
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    ddls = [DDL_EARNINGS_POSTGRES, DDL_SNAPSHOTS_POSTGRES]
    if dialect != "postgresql":
        ddls = [d.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT") for d in ddls]
    with engine.begin() as conn:
        for d in ddls:
            conn.execute(text(d))
        conn.execute(text(_DDL_INDEX))


def _yf_next_earnings(ticker: str, today: date) -> tuple:
    """(date|None, estimate) from yfinance's calendar; the first listed date on/after today."""
    import yfinance as yf
    cal = yf.Ticker(ticker).calendar or {}
    raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if raw is None:
        return None, False
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    ds = sorted({x for x in (_parse_date(getattr(v, "date", lambda: v)() if hasattr(v, "date") else v) for v in raw) if x})
    future = [d for d in ds if d >= today]
    if not future:
        return None, False
    return future[0], len(ds) > 1


def next_earnings_date(ticker: str, *, today: Optional[date] = None, engine=None, lookup: bool = True) -> dict:
    """{'ticker','date','estimate','sessions_to','source'} — memory cache → earnings_calendar table → yfinance."""
    ticker = (ticker or "").strip().upper()
    today = today or date.today()
    cache_h = float(os.getenv("DAI_EARNINGS_CACHE_HOURS", "12"))
    now = time.time()
    rec = _EARN_CACHE.get(ticker)
    fresh = rec and (now - rec["ts"]) < cache_h * 3600 and (rec["date"] is None or rec["date"] >= today)
    if not fresh and engine is not None:
        rec = _db_earnings(engine, ticker, today, cache_h)
        if rec:
            _EARN_CACHE[ticker] = rec
            fresh = True
    if not fresh and lookup and os.getenv("DAI_EARNINGS_LOOKUP", "1") not in ("0", "false", "False"):
        try:
            d, est = _yf_next_earnings(ticker, today)
            rec = {"date": d, "estimate": est, "ts": now, "source": "yfinance"}
            _EARN_CACHE[ticker] = rec
            if engine is not None:
                _db_store_earnings(engine, ticker, rec)
        except Exception as exc:     # noqa: BLE001
            logger.info("earnings lookup failed for %s: %s", ticker, exc)
            rec = rec or {"date": None, "estimate": False, "ts": now, "source": "unavailable"}
    if not rec:
        rec = {"date": None, "estimate": False, "ts": now, "source": "not_shown"}
    d = rec.get("date")
    return {"ticker": ticker, "date": _iso(d), "estimate": bool(rec.get("estimate")),
            "sessions_to": sessions_between(today, d) if d else None, "source": rec.get("source")}


def _db_earnings(engine, ticker: str, today: date, cache_h: float) -> Optional[dict]:
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT next_earnings_date, estimate, fetched_at, source FROM earnings_calendar WHERE ticker = :t"
            ), {"t": ticker}).fetchone()
    except Exception:
        return None
    if not row:
        return None
    fetched = row.fetched_at if isinstance(row.fetched_at, datetime) else _to_dt(row.fetched_at)
    if fetched is None or (datetime.now() - fetched) > timedelta(hours=cache_h):
        return None
    d = _parse_date(row.next_earnings_date)
    if d is not None and d < today:
        return None
    return {"date": d, "estimate": bool(row.estimate), "ts": time.time(), "source": row.source or "cache"}


def _db_store_earnings(engine, ticker: str, rec: dict) -> None:
    from sqlalchemy import text
    try:
        ensure_tables(engine)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM earnings_calendar WHERE ticker = :t"), {"t": ticker})
            conn.execute(text("""
                INSERT INTO earnings_calendar (ticker, next_earnings_date, estimate, fetched_at, source)
                VALUES (:t, :d, :e, :at, :s)
            """), _params(engine, {"t": ticker, "d": rec.get("date"), "e": bool(rec.get("estimate")),
                                   "at": datetime.now(), "s": rec.get("source")}))
    except Exception as exc:     # noqa: BLE001
        logger.info("earnings cache write failed for %s: %s", ticker, exc)


def _to_dt(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def _earnings_flag(sessions_to) -> Optional[str]:
    if sessions_to is None or sessions_to < 0:
        return None
    if sessions_to <= EARNINGS_EXIT_SESSIONS:
        return "reports_within_2"
    if sessions_to <= EARNINGS_REJECT_SESSIONS:
        return "reports_within_5"
    return None


# ----------------------------------------------------------------------------- score
def _macro_points(status: dict, table: dict) -> int:
    st = status.get("sessions_to")
    if status.get("in_window"):
        w = table["window"]
        return w.get(st, w[max(w)])
    if st is not None and st in table["near"]:
        return table["near"][st]
    if status.get("just_printed"):
        return table["post"]
    return 0


def score_event_risk(regime: Optional[str], statuses: dict, holdings_earnings: list) -> tuple:
    """(score 0–100, level, [(name, detail, points)]) — deterministic, documented in the module header."""
    parts = []
    label = (regime or "").upper() or "UNKNOWN"
    base = REGIME_BASE.get(label, 30)
    parts.append(("regime", label, base))
    score = base
    for key, table in (("fomc", FOMC_POINTS), ("cpi", PRINT_POINTS), ("jobs", PRINT_POINTS)):
        s = statuses.get(key) or {}
        p = _macro_points(s, table)
        if p:
            parts.append((key, _when(s), p))
            score += p
    for s in statuses.get("other") or []:
        p = _macro_points(s, PRINT_POINTS)
        if p:
            parts.append(("other", _when(s), p))
            score += p
    exit_pts = sum(EARNINGS_POINTS["exit"] for h in holdings_earnings if h.get("flag") == "reports_within_2")
    rej_pts = sum(EARNINGS_POINTS["reject"] for h in holdings_earnings if h.get("flag") == "reports_within_5")
    exit_pts = min(exit_pts, EARNINGS_POINTS["exit_cap"])
    rej_pts = min(rej_pts, EARNINGS_POINTS["reject_cap"])
    if exit_pts:
        parts.append(("earnings", "holding reports within 2 sessions", exit_pts))
    if rej_pts:
        parts.append(("earnings", "holding reports within 5 sessions", rej_pts))
    score = max(0, min(100, score + exit_pts + rej_pts))
    level = next(name for cut, name in LEVELS if score < cut)
    return score, level, parts


# ----------------------------------------------------------------------------- context
def _regime_allowance(regime: Optional[str]) -> str:
    return {
        "RISK-ON": "up to 3 new BUYs at full rails",
        "MIXED": "at most 2 new BUYs at half size (extension ≤5%)",
        "RISK-OFF": "cash default; at most 1 half-size BUY (oversold reversal or ≤3% above the 20d MA)",
    }.get((regime or "").upper(), "regime unreadable → MIXED: at most 2 new BUYs at half size")


def _allowance(regime: Optional[str], in_window: bool, reason: str, holdings_earnings: list) -> dict:
    if in_window:
        buys = (f"MACRO WINDOW ({reason}) → no full-size BUY: at most 1 half-size BUY with D ≤2%, and every "
                f"BUY/HOLD reason names the event and its date")
    else:
        buys = f"no macro window → regime allowance applies: {_regime_allowance(regime)}"
    soon = [h for h in holdings_earnings if h.get("flag") == "reports_within_2"]
    if soon:
        names = ", ".join(f"{h['ticker']} {h['date']}{' (est.)' if h.get('estimate') else ''}" for h in soon)
        exits = f"{names} → SELL before the print (TRIM to half only if RISK-ON and ≥ +3%)"
    else:
        exits = "none"
    return {"buys": buys, "holdings_reporting_within_2": exits}


def _earnings_rows(tickers, today, engine, lookup, quarantine_seen: set) -> list:
    rows = []
    for t in tickers:
        t = (t or "").strip().upper()
        if not t or t in quarantine_seen or t == "CASH":
            continue
        quarantine_seen.add(t)
        rec = next_earnings_date(t, today=today, engine=engine, lookup=lookup)
        rec["flag"] = _earnings_flag(rec.get("sessions_to"))
        rows.append(rec)
    return rows


def build_event_context(holdings=None, watchlist=None, regime: Optional[str] = None, now_et: Optional[datetime] = None,
                        lookup_earnings: bool = True, engine=None) -> Optional[dict]:
    """Everything the block, the score, the snapshot and the dashboard need for this cycle."""
    if os.getenv("DAI_EVENT_CALENDAR_ENABLED", "1") in ("0", "false", "False"):
        return None
    if now_et is None:
        import pytz
        now_et = datetime.now(pytz.timezone("US/Eastern"))
    today = now_et.date()
    statuses = macro_statuses(today, now_et.time())
    in_window, reason = macro_window(statuses)
    seen: set = set()
    hold_rows = _earnings_rows(holdings or [], today, engine, lookup_earnings, seen)
    watch_rows = _earnings_rows(watchlist or [], today, engine, lookup_earnings, seen)
    score, level, parts = score_event_risk(regime, statuses, hold_rows)
    ctx = {
        "today": today.isoformat(), "weekday": today.strftime("%a"), "time_et": now_et.strftime("%H:%M"),
        "session_state": session_state(now_et), "regime": (regime or "").upper() or None,
        "macro": statuses, "macro_window": in_window, "macro_reason": reason,
        "holdings_earnings": hold_rows, "watchlist_earnings": watch_rows,
        "risk_score": score, "risk_level": level, "score_parts": parts,
        "allowance": _allowance(regime, in_window, reason, hold_rows),
    }
    ctx["block"] = format_event_calendar(ctx)
    return ctx


# ----------------------------------------------------------------------------- prompt block
# Code-owned header (mirrored verbatim in policy_graph/code_blocks.py — the drift test guards it).
EVENT_CALENDAR_HEADER = (
    "# EVENT CALENDAR (scheduled binary events — read this right after the INDEX REGIME line; the EVENT GATE in "
    "your strategy directives decides what each window allows, and it never relaxes an earlier gate)"
)


def _earn_text(rows: list, limit: int = 8) -> str:
    if not rows:
        return "none in play"
    shown, missing = [], []
    for r in rows:
        if r.get("date"):
            st = r.get("sessions_to")
            tag = " (est.)" if r.get("estimate") else ""
            flag = {"reports_within_2": " ⚠ REPORTS ≤2 SESSIONS", "reports_within_5": " ⚠ inside 5-session hold window"}.get(r.get("flag"), "")
            shown.append(f"{r['ticker']} {r['date']}{tag} ({'today' if st == 0 else f'{st} sessions'}){flag}")
        else:
            missing.append(r["ticker"])
    parts = shown[:limit]
    if len(shown) > limit:
        parts.append(f"+{len(shown) - limit} more")
    if missing:
        parts.append("not_shown: " + ", ".join(missing[:limit]))
    return "; ".join(parts) if parts else "none"


def format_event_calendar(ctx: Optional[dict]) -> str:
    if not ctx:
        return ""
    m = ctx.get("macro") or {}
    recent = []
    for key in ("cpi", "jobs", "fomc"):
        s = m.get(key) or {}
        since = s.get("sessions_since")
        if s.get("last") and since is not None and since <= 2:
            ago = "today" if since == 0 else ("1 session ago" if since == 1 else f"{since} sessions ago")
            recent.append(f"{s['label']} {s['last']} ({ago})")
    macro_bits = [_when(m.get("fomc") or {}), _when(m.get("cpi") or {}), _when(m.get("jobs") or {})]
    macro_bits += [_when(s) for s in (m.get("other") or [])]
    fomc = m.get("fomc") or {}
    if fomc.get("next"):
        macro_bits[0] += f" {fomc['release_et']}"
    hold_rows = ctx.get("holdings_earnings") or []
    soon = [r for r in hold_rows if r.get("flag") == "reports_within_2"]
    hold_note = "" if soon or not hold_rows else " — none inside 5 sessions" if not any(r.get("flag") for r in hold_rows) else ""
    allow = ctx.get("allowance") or {}
    lines = [
        EVENT_CALENDAR_HEADER,
        f"# TODAY: {ctx.get('weekday')} {ctx.get('today')} {ctx.get('time_et')} ET ({ctx.get('session_state')}) | "
        f"event-risk score {ctx.get('risk_score')}/100 ({ctx.get('risk_level')}) | MACRO WINDOW: "
        + (f"YES — {ctx.get('macro_reason')}" if ctx.get("macro_window") else "no"),
        "# MACRO: " + " · ".join(macro_bits) + (" · recent: " + ", ".join(recent) if recent else ""),
        f"# EARNINGS (holdings): {_earn_text(hold_rows)}{hold_note}",
        f"# EARNINGS (watchlist): {_earn_text(ctx.get('watchlist_earnings') or [])}",
        f"# ALLOWANCE THIS CYCLE: {ctx.get('regime') or 'regime n/a'}; new BUYs → {allow.get('buys', '')}; "
        f"holdings reporting within 2 sessions: {allow.get('holdings_reporting_within_2', 'none')}",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- snapshots
def record_snapshot(engine, config_hash: str, run_id: Optional[str], ctx: Optional[dict]) -> Optional[int]:
    """One row per decider cycle so the dashboard can show the risk landscape as it was served."""
    if not ctx or engine is None:
        return None
    from sqlalchemy import text
    try:
        ensure_tables(engine)
        m = ctx.get("macro") or {}
        params = {
            "h": config_hash, "r": run_id, "at": datetime.now(), "sd": _parse_date(ctx.get("today")),
            "reg": ctx.get("regime"), "sc": int(ctx.get("risk_score") or 0), "lv": ctx.get("risk_level"),
            "mw": bool(ctx.get("macro_window")), "mr": ctx.get("macro_reason") or None,
            "fd": _parse_date((m.get("fomc") or {}).get("next")), "fs": (m.get("fomc") or {}).get("sessions_to"),
            "cd": _parse_date((m.get("cpi") or {}).get("next")), "cs": (m.get("cpi") or {}).get("sessions_to"),
            "jd": _parse_date((m.get("jobs") or {}).get("next")), "js": (m.get("jobs") or {}).get("sessions_to"),
            "he": json.dumps(ctx.get("holdings_earnings") or [], default=str),
            "we": json.dumps(ctx.get("watchlist_earnings") or [], default=str),
            "al": json.dumps(ctx.get("allowance") or {}, default=str), "bl": ctx.get("block"),
        }
        dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
        sql = """
            INSERT INTO event_risk_snapshots (config_hash, run_id, as_of, session_date, regime, risk_score, risk_level,
                macro_window, macro_reason, fomc_date, fomc_sessions, cpi_date, cpi_sessions, jobs_date, jobs_sessions,
                holdings_earnings, watchlist_earnings, allowance, block)
            VALUES (:h, :r, :at, :sd, :reg, :sc, :lv, :mw, :mr, :fd, :fs, :cd, :cs, :jd, :js, :he, :we, :al, :bl)
        """
        params = _params(engine, params)
        with engine.begin() as conn:
            if dialect == "postgresql":
                return int(conn.execute(text(sql + " RETURNING id"), params).fetchone()[0])
            return int(conn.execute(text(sql), params).lastrowid)
    except Exception as exc:     # noqa: BLE001
        logger.warning("event risk snapshot not recorded: %s", exc)
        return None


def latest_snapshot(engine, config_hash: str) -> Optional[dict]:
    from sqlalchemy import text
    try:
        ensure_tables(engine)
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT as_of, session_date, regime, risk_score, risk_level, macro_window, macro_reason, fomc_date,
                       fomc_sessions, holdings_earnings, allowance, run_id
                FROM event_risk_snapshots WHERE config_hash = :h ORDER BY as_of DESC LIMIT 1
            """), {"h": config_hash}).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "as_of": _to_dt(row.as_of).isoformat() if _to_dt(row.as_of) else str(row.as_of),
        "session_date": _iso(_parse_date(row.session_date)), "regime": row.regime, "risk_score": row.risk_score,
        "risk_level": row.risk_level, "macro_window": bool(row.macro_window), "macro_reason": row.macro_reason,
        "fomc_date": _iso(_parse_date(row.fomc_date)), "fomc_sessions": row.fomc_sessions,
        "holdings_earnings": _loads(row.holdings_earnings, []), "allowance": _loads(row.allowance, {}),
        "run_id": row.run_id,
    }


def _loads(v, default):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------- dashboard series
def _snapshot_days(engine, config_hash: str, start: date) -> dict:
    """{session_date: {"score": max, "regime": last, "flags": max holdings flagged ≤2 sessions, "n": rows}}"""
    from sqlalchemy import text
    out: dict = {}
    try:
        ensure_tables(engine)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT session_date, risk_score, regime, holdings_earnings, macro_window
                FROM event_risk_snapshots WHERE config_hash = :h AND session_date >= :s ORDER BY as_of
            """), _params(engine, {"h": config_hash, "s": start})).fetchall()
    except Exception:
        return out
    for r in rows:
        d = _parse_date(r.session_date)
        if not d:
            continue
        flags = sum(1 for h in _loads(r.holdings_earnings, []) if isinstance(h, dict) and h.get("flag") == "reports_within_2")
        rec = out.setdefault(d, {"score": 0, "regime": None, "flags": 0, "n": 0})
        rec["score"] = max(rec["score"], int(r.risk_score or 0))
        rec["regime"] = r.regime or rec["regime"]
        rec["flags"] = max(rec["flags"], flags)
        rec["n"] += 1
    return out


def _trades_in_window(engine, config_hash: str, start: date) -> list:
    from sqlalchemy import text
    out = []
    params = _params(engine, {"h": config_hash, "s": start})
    try:      # filled buys live inside the decision JSON (jsonb on Postgres; skipped elsewhere)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT d.timestamp, e->>'ticker' AS ticker
                FROM trade_decisions d, jsonb_array_elements(d.data) e
                WHERE d.config_hash = :h AND d.timestamp >= :s AND e->>'action' = 'buy' AND e->>'execution_status' = 'filled'
            """), params).fetchall()
        for r in rows:
            ts = _to_dt(r.timestamp)
            out.append({"date": ts.date().isoformat() if ts else None, "ticker": r.ticker, "action": "buy", "pct": None})
    except Exception:
        pass
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT sell_timestamp, ticker, gain_loss_percentage FROM trade_outcomes
                WHERE config_hash = :h AND sell_timestamp >= :s AND ticker != 'N/A'
                  AND COALESCE(original_reason, '') NOT LIKE '%Market is closed%'
            """), params).fetchall()
        for r in rows:
            ts = _to_dt(r.sell_timestamp)
            pct = float(r.gain_loss_percentage or 0.0) * 100.0
            out.append({"date": ts.date().isoformat() if ts else None, "ticker": r.ticker, "action": "sell", "pct": round(pct, 2)})
    except Exception:
        pass
    return sorted((t for t in out if t["date"]), key=lambda t: t["date"])


def event_risk_payload(engine, config_hash: str, days: int, regime_for: Callable[[date], Optional[str]],
                       holdings=None, now_et: Optional[datetime] = None, horizon_sessions: int = 15) -> dict:
    """Risk-vs-time series for the dashboard: reconstructed history (regime from benchmark history +
    the calendars, earnings flags from recorded snapshots), today's live read, and a forward projection."""
    if now_et is None:
        import pytz
        now_et = datetime.now(pytz.timezone("US/Eastern"))
    today = now_et.date()
    start = today - timedelta(days=int(days))
    snaps = _snapshot_days(engine, config_hash, start)
    snap_today = snaps.get(today)
    # the trader's own regime read (recorded with today's snapshot) beats the benchmark reconstruction
    live_regime = (snap_today or {}).get("regime") or regime_for(today)
    live = build_event_context(holdings=holdings or [], watchlist=[], regime=live_regime, now_et=now_et,
                               lookup_earnings=False, engine=engine)
    series = []
    d = start
    while d <= today:
        if is_session(d):
            snap = snaps.get(d)
            regime = (snap or {}).get("regime") or regime_for(d)
            statuses = macro_statuses(d, None)
            flags = [{"flag": "reports_within_2"}] * ((snap or {}).get("flags") or 0)
            score, level, _ = score_event_risk(regime, statuses, flags)
            if snap:
                score = max(score, snap["score"])
            series.append({"date": d.isoformat(), "score": score, "level": level, "regime": regime or "UNKNOWN",
                           "recorded": bool(snap), "fomc_sessions": statuses["fomc"].get("sessions_to"),
                           "macro_window": macro_window(statuses)[0]})
        d += timedelta(days=1)
    if series and live and not snap_today and series[-1]["date"] == today.isoformat():
        series[-1]["score"] = live["risk_score"]
        series[-1]["level"] = live["risk_level"]
        series[-1]["macro_window"] = live["macro_window"]
    projection = []
    regime_now = (live or {}).get("regime") or live_regime
    hold_flags = [h for h in (live or {}).get("holdings_earnings") or [] if h.get("date")]
    for k in range(1, horizon_sessions + 1):
        fd = add_sessions(today, k)
        statuses = macro_statuses(fd, None)
        flags = []
        for h in hold_flags:
            hd = _parse_date(h["date"])
            st = sessions_between(fd, hd) if hd else None
            f = _earnings_flag(st)
            if f:
                flags.append({"flag": f})
        score, level, _ = score_event_risk(regime_now, statuses, flags)
        projection.append({"date": fd.isoformat(), "score": score, "level": level, "regime": regime_now or "UNKNOWN",
                           "macro_window": macro_window(statuses)[0]})
    events = []
    horizon_end = add_sessions(today, horizon_sessions)
    for kind, label, ds in (("fomc", "FOMC", fomc_dates()), ("cpi", "CPI", cpi_dates()), ("jobs", "Jobs", jobs_dates())):
        events += [{"date": x.isoformat(), "kind": kind, "label": label} for x in ds if start <= x <= horizon_end]
    events += [{"date": x.isoformat(), "kind": "other", "label": lbl} for x, lbl in other_events() if start <= x <= horizon_end]
    for h in hold_flags:
        hd = _parse_date(h["date"])
        if hd and today <= hd <= horizon_end:
            events.append({"date": hd.isoformat(), "kind": "earnings", "label": f"{h['ticker']} earnings"})
    events.sort(key=lambda e: e["date"])
    return {
        "config_hash": config_hash, "days": int(days), "today": today.isoformat(),
        "series": series, "projection": projection, "events": events,
        "trades": _trades_in_window(engine, config_hash, start),
        "live": {k: v for k, v in (live or {}).items() if k not in ("block",)},
        "snapshots_recorded": sum(v["n"] for v in snaps.values()),
        "score_legend": {"regime_base": REGIME_BASE, "fomc": FOMC_POINTS, "print": PRINT_POINTS,
                         "earnings": EARNINGS_POINTS, "levels": [n for _, n in LEVELS]},
    }


if __name__ == "__main__":
    import sys
    tickers = [t.upper() for t in sys.argv[1:]]
    ctx = build_event_context(holdings=tickers[:5], watchlist=tickers[5:], regime=os.getenv("DAI_REGIME"))
    print(ctx["block"] if ctx else "(event calendar disabled)")
    if ctx:
        print()
        print("score parts:", ctx["score_parts"])
