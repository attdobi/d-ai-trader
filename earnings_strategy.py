"""Small, explicit pre-earnings exposure. Pure controls plus read-only audit loaders.

No broker/config/client imports. A model cannot authorize itself: the validator
issues a short-lived in-process ticket using a trusted calendar snapshot. Final
order sizing rechecks that ticket, uses a dollar-bounded LIMIT order, and never
rounds one share above the cap. A stop does not bound an earnings gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import hashlib
import math
import secrets
import re
import threading
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
STRATEGY = "earnings_event"
CONTRACT = "EARNINGS_EVENT_CONTROLS:v1"
MARKER = "[earnings_event]"
MAX_DOLLARS = 500.0
MAX_EQUITY_FRACTION = .05
NORMAL_POSITION_FRACTION = .25
MAX_SESSIONS = 5
MAX_CALENDAR_AGE = timedelta(hours=12)
MAX_CONTEXT_AGE = timedelta(minutes=30)
CORE_WATCHLIST = ("MSFT", "GOOG", "GOOGL", "NFLX", "ORCL", "AMZN", "META", "AAPL", "NVDA", "TSLA")
_TICKETS = {}
_LOCK = threading.Lock()


def number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) and v >= 0 else None
    except (ValueError, TypeError):
        return None


def now_utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("earnings timestamps require an explicit timezone")
    return value.astimezone(timezone.utc)


def event_cap(account_value, normal_position_cap):
    equity, normal = number(account_value), number(normal_position_cap)
    if not equity or not normal:
        return 0.0
    return max(0, math.floor(min(MAX_DOLLARS, equity * MAX_EQUITY_FRACTION,
                                 normal * NORMAL_POSITION_FRACTION) * 100) / 100)


def _event_rows(context):
    rows = (context or {}).get("holdings_earnings", []) + (context or {}).get("watchlist_earnings", [])
    return {str(r.get("ticker") or "").upper(): r for r in rows if isinstance(r, dict)}


def valid_event(row, context, now=None):
    """Return a pre-release event or an auditable reason; never infer a date."""
    now = now_utc(now)
    if not context or context.get("earnings_controls_version") != 1:
        return None, "earnings runtime controls were not supplied this cycle"
    try:
        if not context.get("as_of") or not row.get("fetched_at"):
            return None, "earnings date provenance timestamp is unknown"
        observed = now_utc(context.get("as_of"))
        if not timedelta(0) <= now - observed <= MAX_CONTEXT_AGE:
            return None, "earnings decision context is stale"
        fetched = now_utc(row.get("fetched_at"))
        if not timedelta(0) <= now - fetched <= MAX_CALENDAR_AGE:
            return None, "earnings calendar quote is stale or from the future"
        from event_calendar import sessions_between
        day = datetime.fromisoformat(str(row.get("date"))).date()
        sessions = sessions_between(now.astimezone(ET).date(), day)
    except (TypeError, ValueError, AttributeError):
        return None, "earnings date or its provenance timestamp is unknown"
    if row.get("estimate") is not False or row.get("source") not in ("yfinance", "operator_confirmed_ir"):
        return None, "earnings date is estimated or its source is unsupported"
    if not 0 <= sessions <= MAX_SESSIONS:
        return None, "earnings are outside the next five trading sessions"
    if sessions == 0:
        # Date-only calendars cannot distinguish a report already out this morning.
        release = row.get("release_at")
        if release:
            try:
                if now_utc(release) <= now:
                    return None, "earnings release has already occurred"
            except (ValueError, TypeError, AttributeError):
                return None, "earnings release time is not verified"
        elif row.get("release_timing") != "after_close" or now.astimezone(ET).hour >= 16:
            return None, "today's date needs confirmed future release timing for a pre-earnings entry"
    return dict(row, sessions_to=sessions), ""


def is_event(decision):
    return str(decision.get("strategy") or "standard").lower() == STRATEGY


def release_completed(row, now=None):
    """Only an explicitly supplied release instant permits same-day normal entries."""
    try:
        return (row.get("source") in ("yfinance", "operator_confirmed_ir") and row.get("estimate") is False
                and bool(row.get("release_at")) and now_utc(row["release_at"]) <= now_utc(now))
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass
class EventBook:
    config_hash: str
    context: dict | None
    account_value: float
    normal_position_cap: float
    holdings: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    observed: datetime | None = None
    accepted: set = field(default_factory=set)

    @property
    def cap(self):
        return event_cap(self.account_value, self.normal_position_cap)

    def exposure(self):
        rows = _event_rows(self.context)
        positions = {}
        for holding in self.holdings:
            ticker = str(holding.get("ticker") or "").upper()
            if ticker == "CASH":
                continue
            event = rows.get(ticker) or {}
            sessions = number(event.get("sessions_to"))
            tagged = MARKER in str(holding.get("reason") or "")
            if tagged or sessions is not None and sessions <= MAX_SESSIONS:
                value = number(holding.get("current_value"))
                if value is None:
                    value = number(holding.get("shares"))
                    price = number(holding.get("current_price"))
                    value = value * price if value is not None and price is not None else None
                # Unknown value cannot mean zero room.
                positions[ticker] = value if value is not None else float("inf")
        for item in self.pending:
            ticker = str(item.get("ticker") or "").upper()
            positions[ticker] = max(positions.get(ticker, 0), number(item.get("amount_usd")) or float("inf"))
        for ticker in self.accepted:
            positions.setdefault(ticker, self.cap)
        return positions

    def authorize(self, decision, *, minimum, now=None):
        now = now_utc(now or self.observed)
        ticker = str(decision.get("ticker") or "").upper()
        if not self.config_hash:
            return "earnings account scope is unknown"
        event, why = valid_event(_event_rows(self.context).get(ticker) or {}, self.context, now)
        if why:
            return why
        intent = decision.get("earnings_event")
        if not isinstance(intent, dict) or intent.get("date") != event["date"]:
            return "earnings strategy must name the supplied earnings date"
        if intent.get("hold_through") is not True or intent.get("gap_risk_accepted") is not True:
            return "earnings strategy must explicitly accept holding through the release and full-notional gap risk"
        exposure = self.exposure()
        if exposure:
            return "one earnings-event exposure is already held, pending or reserved"
        cap = self.cap
        if cap < minimum:
            return f"earnings cap ${cap:.2f} cannot meet the existing minimum buy ${minimum:.2f}"
        amount = number(decision.get("amount_usd"))
        if not amount:
            return "earnings amount must be positive and finite"
        if min(amount, cap) < minimum:
            return f"earnings allocation is below the existing minimum buy ${minimum:.2f}"
        decision["amount_usd_requested"] = amount
        decision["amount_usd"] = min(amount, cap)
        decision["strategy"] = STRATEGY
        with _LOCK:
            _sweep(now)
            if any(t["config_hash"] == self.config_hash for t in _TICKETS.values()):
                return "another earnings-event order is reserved in this process"
            token = secrets.token_hex(24)
            _TICKETS[token] = {"config_hash": self.config_hash, "ticker": ticker, "cap_usd": cap,
                               "minimum_usd": minimum,
                               "event_date": event["date"], "issued_at": now.isoformat(),
                               "context": json.loads(json.dumps(self.context)),
                               "expires_at": (now + timedelta(minutes=30)).isoformat()}
        decision["_earnings_authorization"] = token
        decision["earnings_event_controls"] = {"version": 1, "cap_usd": cap, "account_value": self.account_value,
              "source": event["source"], "fetched_at": event["fetched_at"], "date": event["date"],
              "sessions_to": event["sessions_to"], "gap_loss_bound": "full position notional", "order_type": "LIMIT"}
        if MARKER not in str(decision.get("reason") or ""):
            decision["reason"] = f"{MARKER} " + str(decision.get("reason") or "")
        self.accepted.add(ticker)
        return ""


def _sweep(now):
    for token in list(_TICKETS):
        if now_utc(_TICKETS[token]["expires_at"]) < now:
            _TICKETS.pop(token, None)


def release(decision):
    with _LOCK:
        _TICKETS.pop(decision.get("_earnings_authorization"), None)


def mark_submitted(decision, *, now=None):
    """Reserve the DAY slot before broker I/O, including an ambiguous timeout."""
    now = now_utc(now)
    with _LOCK:
        auth = _TICKETS.get(decision.get("_earnings_authorization"))
        if auth is None or auth.get("submitted"):
            raise ValueError("earnings order authorization is missing or already submitted")
        auth["submitted"] = True
        auth["expires_at"] = now.astimezone(ET).replace(hour=16, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()


def execution_limit(decision, price, *, config_hash, market_open, account_value=None,
                    normal_position_cap=None, holdings=None, pending=None, now=None):
    """Validate server ticket and return (whole shares, limit price, cap) or raise.

    LIMIT price bounds notional at the broker; a last quote plus MARKET would not.
    """
    if not is_event(decision):
        return None
    now = now_utc(now)
    if not market_open:
        raise ValueError("earnings entries execute only during the regular market session")
    with _LOCK:
        _sweep(now)
        auth = dict(_TICKETS.get(decision.get("_earnings_authorization")) or {})
    if not auth or auth["config_hash"] != config_hash or auth["ticker"] != str(decision.get("ticker") or "").upper():
        raise ValueError("earnings entry lacks a current server authorization")
    if auth.get("submitted"):
        raise ValueError("earnings order authorization was already submitted")
    event, why = valid_event(_event_rows(auth["context"]).get(auth["ticker"]) or {}, auth["context"], now)
    if why:
        raise ValueError(why)
    if holdings is None or pending is None:
        raise ValueError("current earnings holdings/open-order exposure could not be verified")
    book = EventBook(config_hash, auth["context"], account_value or 0, normal_position_cap or 0,
                     list(holdings), list(pending))
    if book.exposure():
        raise ValueError("an earnings exposure is already held or pending")
    cap = auth["cap_usd"]
    if account_value is not None or normal_position_cap is not None:
        cap = min(cap, event_cap(account_value, normal_position_cap))
    quote = number(price)
    amount = number(decision.get("amount_usd"))
    if not quote or not amount:
        raise ValueError("earnings entry has no usable quote or allocation")
    limit_price = math.floor(quote * 100 + 1e-8) / 100
    shares = math.floor(min(amount, cap) / quote + 1e-9) if limit_price > 0 else 0
    requested = decision.get("shares_override")
    if requested is not None:
        shares = min(shares, int(requested))
    if shares <= 0:
        raise ValueError(f"one whole share exceeds the earnings allocation/cap ${min(amount, cap):.2f}")
    if shares * limit_price > cap + 1e-8:
        raise ValueError("earnings order exceeds the event exposure cap")
    if shares * limit_price < auth["minimum_usd"] - 1e-8:
        raise ValueError("whole-share earnings order cannot meet the existing minimum buy without exceeding its cap")
    return shares, limit_price, cap


def format_controls(context, holdings, cash, normal_position_cap, *, config_hash):
    equity = (number(cash) or 0) + sum(number(h.get("current_value")) or 0 for h in holdings)
    book = EventBook(config_hash, context, equity, normal_position_cap, list(holdings))
    return (f"# {CONTRACT}\nSeparate pre-earnings strategy: evaluate supplied upcoming earnings today before release or 1–5 trading sessions out. "
            f"Event cap this cycle: ${book.cap:.2f} = min($500, 5% account value, 25% ordinary position cap). "
            f"At most one event exposure; current held-event count: {len(book.exposure())}. "
            "Never bypass cash, minimum buy, priced stops, quarantine, correlation or ordinary position limits. "
            "An earnings-event BUY must set strategy=earnings_event and earnings_event={date: exact supplied date, hold_through: true, gap_risk_accepted: true}. "
            "A stop does not cap a release gap: the entire position notional is at risk. Runtime uses capped whole-share LIMIT orders. "
            "Unknown, stale or estimated earnings dates cannot use this exception. Date-only today needs future release timing. "
            "Ordinary after-release opportunities remain standard strategy. This runtime block is required for every earnings exception.")


def load_run_context(engine, config_hash, run_id):
    """Read the exact supplied calendar, never current news or model-provided data."""
    if not run_id:
        return None
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT as_of, session_date, holdings_earnings, watchlist_earnings, allowance
                FROM event_risk_snapshots WHERE config_hash=:h AND run_id=:r ORDER BY id DESC LIMIT 1"""),
                               {"h": config_hash, "r": run_id}).mappings().first()
            prompt = conn.execute(text("""SELECT user_prompt FROM decider_inputs WHERE config_hash=:h AND run_id=:r
                AND call_kind='decide' ORDER BY id DESC LIMIT 1"""), {"h":config_hash,"r":run_id}).scalar()
        if not row or not re.search(r"(?:^|\n)# " + re.escape(CONTRACT) + r"\nSeparate pre-earnings strategy:", str(prompt or "")):
            return None
        allowance = row["allowance"] if isinstance(row["allowance"], dict) else json.loads(row["allowance"] or "{}")
        if allowance.get("earnings_controls_version") != 1:
            return None
        observed = row["as_of"]
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed)
        if observed.tzinfo is None:
            observed = observed.astimezone()
        return {"as_of": observed.astimezone(timezone.utc).isoformat(), "today": str(row["session_date"]),
                "earnings_controls_version": 1, "holdings_earnings": json.loads(row["holdings_earnings"] or "[]"),
                "watchlist_earnings": json.loads(row["watchlist_earnings"] or "[]")}
    except Exception:
        return None


def pending_orders(engine, config_hash, *, now=None):
    """Accepted DAY event orders reserve the slot until close or terminal status."""
    now = now_utc(now)
    from sqlalchemy import text
    try:
        start = now.astimezone(PT).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        with engine.connect() as conn:
            records = conn.execute(text("SELECT data FROM trade_decisions WHERE config_hash=:h AND timestamp>=:t ORDER BY id"),
                                   {"h": config_hash, "t": start}).scalars().all()
        return _pending_records(records, now)
    except Exception:
        # Unknown open orders must not become available event capacity.
        return [{"ticker": "UNKNOWN_ORDER_STATE", "amount_usd": float("inf")}]


def _pending_records(records, now):
    pending = {}
    for raw in records:
        rows = raw if isinstance(raw, list) else json.loads(raw)
        for d in rows:
            if not isinstance(d, dict) or not is_event(d) or d.get("action") != "buy":
                continue
            reservation = d.get("earnings_submission") or {}
            key = reservation.get("reservation_id") or d.get("order_id")
            if not key:
                continue
            status = str(d.get("execution_status") or "").lower()
            # FILLED also consumes today's slot: local holdings may not yet be
            # written/synced. Only explicit broker terminal non-fills clear it.
            if status in ("rejected", "canceled", "cancelled", "expired"):
                pending.pop(str(key), None)
            else:
                pending[str(key)] = d
    return list(pending.values()) if now.astimezone(ET).hour < 16 else []


def reserve_submission(engine, decision, config_hash, *, now=None):
    """Durably claim one DAY slot before broker I/O, serialized across processes.

    Unknown broker acceptance remains reserved after a crash or a timeout. This
    writes only the already validated exact run/ticker row, never a model token.
    """
    from sqlalchemy import text
    now = now_utc(now)
    token = decision.get("_earnings_authorization")
    run_id = decision.get("_earnings_run_id")
    if not token or not run_id:
        raise ValueError("earnings submission requires a saved validated run")
    start = now.astimezone(PT).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    dialect = getattr(getattr(engine, "dialect", None), "name", "")
    with engine.begin() as conn:
        if dialect == "postgresql":
            key = int.from_bytes(hashlib.sha256(("earnings:" + config_hash).encode()).digest()[:8], "big", signed=True)
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key":key})
        elif dialect == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise ValueError("earnings reservation requires a supported transactional database")
        records=conn.execute(text("SELECT data FROM trade_decisions WHERE config_hash=:h AND timestamp>=:t ORDER BY id"),
                             {"h":config_hash,"t":start}).scalars().all()
        if _pending_records(records,now):
            raise ValueError("an earnings submission is already reserved for this account today")
        row=conn.execute(text("SELECT id,data FROM trade_decisions WHERE config_hash=:h AND run_id=:r ORDER BY id DESC LIMIT 1"),
                         {"h":config_hash,"r":run_id}).mappings().first()
        if not row:
            raise ValueError("validated earnings decision was not saved")
        stored=row["data"] if isinstance(row["data"],list) else json.loads(row["data"])
        match=next((d for d in stored if isinstance(d,dict) and is_event(d) and d.get("action")=="buy"
                    and str(d.get("ticker") or "").upper()==str(decision.get("ticker") or "").upper()
                    and d.get("_earnings_authorization")==token),None)
        if match is None:
            raise ValueError("saved earnings decision does not match its server authorization")
        submission={"reservation_id":secrets.token_hex(24),"submitted_at":now.isoformat(),
                    "expires_at":now.astimezone(ET).replace(hour=16,minute=0,second=0,microsecond=0).isoformat(),
                    "scope":"one earnings submission per account per DAY session"}
        match.update(execution_status="submitting",earnings_submission=submission)
        conn.execute(text("UPDATE trade_decisions SET data=:d WHERE id=:id"),{"d":json.dumps(stored),"id":row["id"]})
    decision.update(execution_status="submitting",earnings_submission=submission)
