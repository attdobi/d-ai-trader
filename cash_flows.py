"""External cash transfers (deposits / withdrawals) and flow-adjusted gains.

A deposit is not a gain. Before this module the Dashboard's Net Gain/Loss was "liquidation value minus
the first-seen baseline" and its performance chart "value minus the first snapshot", so the $700 and
$22.82 journals of 2026-09-23/25 read as $722.82 of trading profit (and the June/July transfers before
them as another $981). Only the Feedback tab's System vs Market TWR (benchmark_tracker.py) stripped them.

Rows live in `external_cash_flows`, one row per transfer, scoped by config_hash:
  * source 'schwab' — inserted by benchmark_tracker.refresh_cash_flows from the Schwab transactions API
    (txn_key = activityId, ON CONFLICT DO NOTHING: the sync never rewrites an existing row, so an
    operator's `excluded` flag and every manual row survive it);
  * source 'manual' — entered on the Dashboard's Cash transfers card (txn_key = 'manual:<uuid>').

Counting rules (`mark_counted`):
  * an excluded row never counts (the operator's toggle for a Schwab row that is not an external
    transfer, e.g. an internal journal);
  * a manual row within ±3 days and ±$0.01 of a counted Schwab row duplicates it and does not count.
    Matching is one-to-one: a second manual entry of the same amount claims a second transfer.

Gain math:
  * headline net gain = current value − baseline − net counted flows dated on/after the baseline date;
  * percent = Modified Dietz over the same period: (V1 − V0 − ΣF) / (V0 + Σ w_i·F_i), w_i being the
    share of the period flow i was invested;
  * chart series = value − first value − cumulative flows up to each point. Each flow is pinned to the
    snapshot step whose value jump it explains (`align_flows`): Schwab dates a transfer when it is
    initiated (UTC) and liquidationValue often moves a day later, so calendar pinning drew a ±$1,853
    spike for a day around the 2026-07-21/22 transfers.

Config-free: the engine and the config hash are passed in; nothing here imports config or reads
os.environ (the dashboard routes in cash_flow_routes.py and the TWR in benchmark_tracker.py call in).

Public API:
    ensure_schema(engine)
    list_flows(engine, config_hash, start=None, end=None) -> [flow dict]        # deduped, counted flags set
    add_manual_flow(engine, config_hash, flow_date, amount, direction, note='', today=None) -> flow dict
    delete_manual_flow(engine, config_hash, flow_id) / set_excluded(engine, config_hash, flow_id, excluded)
    mark_counted(flows) / counted_pairs(flows) / net_flows(flows, start, end) / flow_totals(flows, since)
    modified_dietz(begin_value, end_value, flows, start, end) -> fraction | None
    align_flows(timestamps, flows, values=None) / cumulative_flow_series(timestamps, flows, values=None)
    flow_adjusted_gain(current_value, baseline_value, flows, baseline_at, as_of) -> dict
    adjusted_performance_series(points, flows) -> [dict]
"""
from __future__ import annotations

import itertools
import math
import uuid
import weakref
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy import text

TABLE = "external_cash_flows"
SOURCE_SCHWAB = "schwab"
SOURCE_MANUAL = "manual"
MANUAL_KEY_PREFIX = "manual:"
DUPLICATE_WINDOW_DAYS = 3
DUPLICATE_TOLERANCE = 0.01
NOTE_MAX_CHARS = 200
MAX_MANUAL_AMOUNT = 10_000_000.0       # sanity rail for a typo'd amount, not a business limit
EARLIEST_FLOW_DATE = date(2000, 1, 1)
DIRECTIONS = ("deposit", "withdrawal")

DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS external_cash_flows (
    id SERIAL PRIMARY KEY,
    config_hash TEXT NOT NULL,
    txn_key TEXT UNIQUE NOT NULL,
    flow_date DATE NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    description TEXT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'schwab',
    note TEXT,
    excluded BOOLEAN DEFAULT FALSE
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")

# Columns added to tables created before manual entries existed (benchmark_tracker's original DDL).
# The DEFAULTs backfill existing rows: every legacy row is a Schwab row and nothing is excluded.
MIGRATION_COLUMNS = (
    ("source", "TEXT DEFAULT 'schwab'"),
    ("note", "TEXT"),
    ("excluded", "BOOLEAN DEFAULT FALSE"),
)
ALTER_POSTGRES = {
    col: f"ALTER TABLE external_cash_flows ADD COLUMN IF NOT EXISTS {col} {typ}"
    for col, typ in MIGRATION_COLUMNS
}
DDL_INDEX = "CREATE INDEX IF NOT EXISTS ix_external_cash_flows_cfg ON external_cash_flows (config_hash, flow_date)"

_SELECT_FULL = """
    SELECT id, txn_key, flow_date, amount, description, recorded_at, source, note, excluded
    FROM external_cash_flows WHERE config_hash = :c
"""
_SELECT_LEGACY = """
    SELECT id, txn_key, flow_date, amount, description, recorded_at
    FROM external_cash_flows WHERE config_hash = :c
"""


class CashFlowError(ValueError):
    """Bad input (HTTP 400)."""


class NotFound(LookupError):
    """No such transfer for this config (HTTP 404)."""


# ----------------------------------------------------------------------------- coercion helpers
def _is_pg(engine) -> bool:
    return (getattr(getattr(engine, "dialect", None), "name", "") or "") == "postgresql"


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise CashFlowError(f"not a date: {value!r}")


def _as_datetime(value) -> datetime:
    """Naive datetime for weighting (a date is its midnight; tz-aware values drop their zone —
    portfolio_history timestamps are naive local time)."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, dtime.min)
    if isinstance(value, str):
        s = value.strip()
        try:
            return datetime.fromisoformat(s).replace(tzinfo=None)
        except ValueError:
            return datetime.combine(date.fromisoformat(s[:10]), dtime.min)
    raise CashFlowError(f"not a timestamp: {value!r}")


as_date = _as_date
as_datetime = _as_datetime


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "t", "yes", "on")
    return bool(value)


def format_money(amount: float) -> str:
    """$700 / $22.82 / $1,704.29 (no sign)."""
    a = abs(float(amount))
    return f"${a:,.0f}" if abs(a - round(a)) < 0.005 else f"${a:,.2f}"


def flow_label(amount: float) -> str:
    """'+$700 deposit' / '−$500 withdrawal' — the chart annotation text."""
    amount = float(amount)
    return f"{'+' if amount >= 0 else '−'}{format_money(amount)} {'deposit' if amount >= 0 else 'withdrawal'}"


# ----------------------------------------------------------------------------- schema
_SCHEMA_READY = weakref.WeakSet()


def _columns(conn, pg: bool) -> set:
    if pg:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'external_cash_flows' AND table_schema = current_schema()"
        )).fetchall()
        return {r[0] for r in rows}
    return {r[1] for r in conn.execute(text("PRAGMA table_info(external_cash_flows)")).fetchall()}


def ensure_schema(engine) -> None:
    """Create the table / add the manual-entry columns (idempotent; checked once per engine).

    init_database.py runs the same DDL on Postgres; this lazy path mirrors the CREATE TABLE IF NOT
    EXISTS that benchmark_tracker always ran, so a dashboard started before init_database still works.
    ALTERs are issued only for columns that are actually missing (no lock on every request)."""
    try:
        if engine in _SCHEMA_READY:
            return
    except TypeError:            # an engine stub without weakref support: just run it
        pass
    pg = _is_pg(engine)
    with engine.begin() as conn:
        conn.execute(text(DDL_POSTGRES if pg else DDL_SQLITE))
        have = _columns(conn, pg)
        for col, typ in MIGRATION_COLUMNS:
            if col not in have:
                conn.execute(text(ALTER_POSTGRES[col] if pg else f"ALTER TABLE external_cash_flows ADD COLUMN {col} {typ}"))
        conn.execute(text(DDL_INDEX))
    try:
        _SCHEMA_READY.add(engine)
    except TypeError:
        pass


# ----------------------------------------------------------------------------- rows
def _row_dict(m) -> dict:
    key = str(m["txn_key"] or "")
    # The key prefix is authoritative: a manual row stays manual even on a legacy-column read.
    source = SOURCE_MANUAL if key.startswith(MANUAL_KEY_PREFIX) else (m.get("source") or SOURCE_SCHWAB)
    return {
        "id": int(m["id"]),
        "txn_key": key,
        "date": _as_date(m["flow_date"]),
        "amount": float(m["amount"]),
        "description": m.get("description") or "",
        "note": m.get("note") or "",
        "source": source,
        "excluded": _bool(m.get("excluded") or False),
        "recorded_at": m.get("recorded_at"),
        "duplicate_of": None,
        "counted": True,
    }


def _select_rows(engine, config_hash: str) -> list:
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_SELECT_FULL), {"c": config_hash}).fetchall()
    except Exception:
        # Table predates the migration (init_database not re-run, schema not writable): every row
        # is a Schwab row, nothing is excluded — exactly today's behaviour.
        with engine.connect() as conn:
            rows = conn.execute(text(_SELECT_LEGACY), {"c": config_hash}).fetchall()
    return [_row_dict(r._mapping) for r in rows]


def mark_counted(flows: list, window_days: int = DUPLICATE_WINDOW_DAYS, tolerance: float = DUPLICATE_TOLERANCE) -> list:
    """Set `counted` and `duplicate_of` on each flow dict (in place) and return the list.

    Excluded rows never count. A manual row whose signed amount is within `tolerance` of a counted
    Schwab row dated within `window_days` duplicates it (nearest date first, then lowest id), and each
    Schwab row absorbs at most one manual row."""
    for f in flows:
        f["duplicate_of"] = None
        f["counted"] = not f.get("excluded")
    autos = [f for f in flows if f.get("source") != SOURCE_MANUAL and f["counted"]]
    manual = sorted((f for f in flows if f.get("source") == SOURCE_MANUAL and f["counted"]),
                    key=lambda f: (f["date"], f["id"]))
    claimed = set()
    for m in manual:
        best = None
        for a in autos:
            if a["id"] in claimed:
                continue
            gap = abs((a["date"] - m["date"]).days)
            if gap > window_days or round(abs(a["amount"] - m["amount"]), 6) > tolerance:
                continue
            if best is None or (gap, a["id"]) < (best[0], best[1]["id"]):
                best = (gap, a)
        if best is not None:
            claimed.add(best[1]["id"])
            m["duplicate_of"] = best[1]["id"]
            m["counted"] = False
    return flows


def list_flows(engine, config_hash: str, start=None, end=None) -> list:
    """Every transfer of this config (Schwab + manual), oldest first, with `counted` / `duplicate_of`
    set. Duplicates are resolved over ALL rows before the date filter, so a window edge cannot split a
    manual entry from the Schwab row it duplicates."""
    flows = mark_counted(_select_rows(engine, config_hash))
    lo = _as_date(start) if start is not None else None
    hi = _as_date(end) if end is not None else None
    flows = [f for f in flows if (lo is None or f["date"] >= lo) and (hi is None or f["date"] <= hi)]
    flows.sort(key=lambda f: (f["date"], f["id"]))
    return flows


def counted_pairs(flows: list, start=None, end=None) -> list:
    """[(date, amount)] of the counted flows, optionally limited to start <= date <= end."""
    lo = _as_date(start) if start is not None else None
    hi = _as_date(end) if end is not None else None
    return [(f["date"], f["amount"]) for f in flows
            if f.get("counted") and (lo is None or f["date"] >= lo) and (hi is None or f["date"] <= hi)]


def net_flows(flows: list, start=None, end=None) -> float:
    """Net counted flow (deposits positive) dated start <= date <= end (either bound optional)."""
    return round(sum(a for _, a in counted_pairs(flows, start, end)), 2)


def flow_totals(flows: list, since=None) -> dict:
    pairs = counted_pairs(flows, start=since)
    deposits = sum(a for _, a in pairs if a > 0)
    withdrawals = -sum(a for _, a in pairs if a < 0)
    return {
        "net": round(deposits - withdrawals, 2),
        "deposits": round(deposits, 2),
        "withdrawals": round(withdrawals, 2),
        "count": len(pairs),
        "excluded": sum(1 for f in flows if f.get("excluded")),
        "duplicates": sum(1 for f in flows if f.get("duplicate_of") is not None),
        "since": _as_date(since).isoformat() if since is not None else None,
    }


def serialize_flow(f: dict, baseline_date=None) -> dict:
    """JSON-ready flow (ISO dates, display label, whether it falls inside the gain period)."""
    out = dict(f)
    out["date"] = f["date"].isoformat()
    ra = f.get("recorded_at")
    out["recorded_at"] = ra.isoformat() if hasattr(ra, "isoformat") else (str(ra) if ra else None)
    out["label"] = flow_label(f["amount"])
    out["direction"] = "deposit" if f["amount"] >= 0 else "withdrawal"
    out["in_gain_period"] = baseline_date is None or f["date"] >= _as_date(baseline_date)
    return out


# ----------------------------------------------------------------------------- manual entries
def validate_manual_flow(flow_date, amount, direction, note=None, today=None):
    """(date, signed amount, note) or CashFlowError. The amount is a positive magnitude; the
    direction (deposit | withdrawal) gives the sign. Dates in the future are rejected."""
    today = _as_date(today) if today is not None else date.today()
    if flow_date in (None, ""):
        raise CashFlowError("date is required (YYYY-MM-DD)")
    try:
        d = _as_date(flow_date)
    except (CashFlowError, ValueError, TypeError):
        raise CashFlowError(f"date must be YYYY-MM-DD, got {flow_date!r}")
    if d > today:
        raise CashFlowError(f"date {d.isoformat()} is in the future")
    if d < EARLIEST_FLOW_DATE:
        raise CashFlowError(f"date {d.isoformat()} is too far in the past")
    if isinstance(amount, bool):
        raise CashFlowError("amount must be a number")
    try:
        value = float(str(amount).replace(",", "").replace("$", "").strip()) if isinstance(amount, str) else float(amount)
    except (TypeError, ValueError):
        raise CashFlowError(f"amount must be a number, got {amount!r}")
    if not math.isfinite(value) or value <= 0:
        raise CashFlowError("amount must be greater than 0 (pick deposit or withdrawal for the sign)")
    value = round(value, 2)
    if value < 0.01:
        raise CashFlowError("amount must be at least $0.01")
    if value > MAX_MANUAL_AMOUNT:
        raise CashFlowError(f"amount {value:,.2f} exceeds the {MAX_MANUAL_AMOUNT:,.0f} sanity limit")
    direction = str(direction or "").strip().lower()
    if direction not in DIRECTIONS:
        raise CashFlowError("direction must be 'deposit' or 'withdrawal'")
    note = "" if note is None else str(note).strip()
    if len(note) > NOTE_MAX_CHARS:
        raise CashFlowError(f"note is limited to {NOTE_MAX_CHARS} characters")
    return d, (value if direction == "deposit" else -value), note


def _get_flow(engine, config_hash: str, flow_id: int) -> dict:
    for f in list_flows(engine, config_hash):
        if f["id"] == int(flow_id):
            return f
    raise NotFound(f"transfer {flow_id} not found for this configuration")


def add_manual_flow(engine, config_hash: str, flow_date, amount, direction, note=None, today=None) -> dict:
    """Insert a manual transfer; returns it with its duplicate status resolved."""
    d, signed, note = validate_manual_flow(flow_date, amount, direction, note, today=today)
    ensure_schema(engine)
    key = f"{MANUAL_KEY_PREFIX}{uuid.uuid4().hex}"
    description = note or f"Manual {'deposit' if signed > 0 else 'withdrawal'}"
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO external_cash_flows (config_hash, txn_key, flow_date, amount, description, source, note, excluded)
            VALUES (:c, :k, :d, :a, :desc, :src, :note, :ex)
        """), {"c": config_hash, "k": key, "d": d if _is_pg(engine) else d.isoformat(), "a": signed,
               "desc": description[:NOTE_MAX_CHARS], "src": SOURCE_MANUAL, "note": note or None, "ex": False})
        new_id = conn.execute(text("SELECT id FROM external_cash_flows WHERE txn_key = :k"), {"k": key}).scalar()
    return _get_flow(engine, config_hash, new_id)


def delete_manual_flow(engine, config_hash: str, flow_id: int) -> dict:
    """Delete a manual transfer (Schwab rows are excluded instead, so the sync cannot re-insert them)."""
    f = _get_flow(engine, config_hash, flow_id)
    if f["source"] != SOURCE_MANUAL:
        raise CashFlowError("only manual transfers can be deleted — exclude a Schwab transfer instead")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM external_cash_flows WHERE id = :i AND config_hash = :c AND txn_key = :k"),
                     {"i": f["id"], "c": config_hash, "k": f["txn_key"]})
    return f


def set_excluded(engine, config_hash: str, flow_id: int, excluded: bool) -> dict:
    """Exclude (or re-include) a Schwab transfer from every gain figure."""
    f = _get_flow(engine, config_hash, flow_id)
    if f["source"] == SOURCE_MANUAL:
        raise CashFlowError("manual transfers are deleted, not excluded")
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE external_cash_flows SET excluded = :ex WHERE id = :i AND config_hash = :c"),
                     {"ex": bool(excluded), "i": f["id"], "c": config_hash})
    return _get_flow(engine, config_hash, flow_id)


# ----------------------------------------------------------------------------- returns
def modified_dietz(begin_value, end_value, flows, start, end):
    """Modified Dietz return (a fraction) over [start, end].

    flows: [(when, amount)], deposits positive; `when` is a date (its midnight) or a datetime. Each
    flow is weighted by the share of the period it was invested, clamped to [0, 1] (a flow dated on
    the start day before the start time weighs 1). None when the capital base is not positive."""
    t0, t1 = _as_datetime(start), _as_datetime(end)
    period = (t1 - t0).total_seconds()
    net = weighted = 0.0
    for when, amount in flows:
        amount = float(amount)
        net += amount
        if period > 0:
            w = (period - (_as_datetime(when) - t0).total_seconds()) / period
            weighted += min(1.0, max(0.0, w)) * amount
    denom = float(begin_value) + weighted
    if denom <= 0:
        return None
    return (float(end_value) - float(begin_value) - net) / denom


def align_flows(timestamps, flows, values=None, settle_days=3, grace_days=1, top_k=6, max_combos=50000):
    """First series index each flow is embedded in (None = not visible in the series yet).

    Without values: the first point dated on/after the flow's date. With values: the snapshot step
    (i-1 → i) inside [date - grace_days, date + settle_days] whose value jump the flow explains,
    solved jointly for flows that share candidate steps by minimizing the total unexplained change
    (a −$1,853 / +$1,394.97 pair that posted as one −$459.61 step lands on that step together).
    Candidates are each flow's `top_k` largest moves in its window; clusters too large for an
    exhaustive search fall back to largest-flow-first greedy."""
    days = [_as_date(t) for t in timestamps]
    n = len(days)
    pairs = [(_as_date(d), float(a)) for d, a in flows]

    def calendar_index(d):
        for i, day in enumerate(days):
            if day >= d:
                return i
        return None

    result = [calendar_index(d) for d, _ in pairs]
    if values is None or n < 2 or len(values) != n:
        return result
    vals = [float(v or 0.0) for v in values]
    delta = [0.0] + [vals[i] - vals[i - 1] for i in range(1, n)]

    cands = []
    for d, _ in pairs:
        lo, hi = d - timedelta(days=grace_days), d + timedelta(days=settle_days)
        steps = [i for i in range(1, n) if days[i] >= lo and days[i - 1] <= hi]
        steps.sort(key=lambda i: (-abs(delta[i]), i))
        cands.append(steps[:top_k])

    # Cluster flows that share any candidate step (union-find over the flow indices).
    parent = list(range(len(pairs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for k, steps in enumerate(cands):
        for s in steps:
            if s in owner:
                parent[find(k)] = find(owner[s])
            else:
                owner[s] = k
    clusters = {}
    for k in range(len(pairs)):
        if cands[k]:
            clusters.setdefault(find(k), []).append(k)

    for members in clusters.values():
        union_steps = sorted({s for k in members for s in cands[k]})

        def residual(assignment):
            assigned = {}
            for k, s in zip(members, assignment):
                assigned[s] = assigned.get(s, 0.0) + pairs[k][1]
            return sum(abs(delta[s] - assigned.get(s, 0.0)) for s in union_steps)

        combos = 1
        for k in members:
            combos *= len(cands[k])
        if combos <= max_combos:
            best = min(itertools.product(*[cands[k] for k in members]), key=residual)
            for k, s in zip(members, best):
                result[k] = s
        else:
            assigned = {}
            for k in sorted(members, key=lambda k: -abs(pairs[k][1])):
                amt = pairs[k][1]
                s = min(cands[k], key=lambda s: (abs(delta[s] - assigned.get(s, 0.0) - amt), s))
                assigned[s] = assigned.get(s, 0.0) + amt
                result[k] = s
    return result


def cumulative_flow_series(timestamps, flows, values=None, **align_kw) -> list:
    """Cumulative counted flow embedded in each point of a value series (see align_flows)."""
    idx = align_flows(timestamps, flows, values=values, **align_kw)
    per_point = [0.0] * len(timestamps)
    for (_, amount), i in zip(flows, idx):
        if i is not None:
            per_point[i] += float(amount)
    out, running = [], 0.0
    for v in per_point:
        running += v
        out.append(round(running, 2))
    return out


def flow_adjusted_gain(current_value, baseline_value, flows, baseline_at=None, as_of=None) -> dict:
    """Headline Net Gain/Loss with external transfers removed.

    flows: [(date, amount)] counted flows (see counted_pairs); those dated on/after the baseline date
    are subtracted. The percent is Modified Dietz from baseline_at to as_of; without both timestamps
    it falls back to the mid-period Dietz convention (every flow weighted 1/2)."""
    cur = float(current_value or 0.0)
    base = float(baseline_value or 0.0)
    start_day = _as_date(baseline_at) if baseline_at is not None else None
    in_period = [(_as_date(d), float(a)) for d, a in flows if start_day is None or _as_date(d) >= start_day]
    net = sum(a for _, a in in_period)
    raw = cur - base
    gain = raw - net
    method = "modified_dietz"
    md = None
    if baseline_at is not None and as_of is not None:
        md = modified_dietz(base, cur, in_period, baseline_at, as_of)
    else:
        method = "dietz_midpoint"
        denom = base + 0.5 * net
        md = gain / denom if denom > 0 else None
    deposits = sum(a for _, a in in_period if a > 0)
    withdrawals = -sum(a for _, a in in_period if a < 0)
    return {
        "net_gain_loss": round(gain, 2),
        "net_gain_loss_raw": round(raw, 2),
        "net_percentage_gain": round(md * 100.0, 4) if md is not None else 0.0,
        "net_percentage_gain_raw": round(raw / base * 100.0, 4) if base else 0.0,
        "net_flows": round(net, 2),
        "deposits": round(deposits, 2),
        "withdrawals": round(withdrawals, 2),
        "flow_count": len(in_period),
        "baseline_value": round(base, 2),
        "baseline_date": start_day.isoformat() if start_day else None,
        "method": method,
    }


def adjusted_performance_series(points, flows, **align_kw) -> list:
    """Per-point gain vs the first point with transfers removed.

    points: [(timestamp, value)] in time order; flows: [(date, amount)] counted flows dated on/after
    the first point's date. Each row: net_gain_loss (value − first value − cumulative flows),
    net_percentage_gain (Modified Dietz from the first point, %), their *_raw twins, cumulative_flows
    and `flows` (the amounts that took effect at this point)."""
    if not points:
        return []
    ts = [p[0] for p in points]
    vals = [float(p[1] or 0.0) for p in points]
    base, t0 = vals[0], ts[0]
    pairs = [(_as_date(d), float(a)) for d, a in flows]
    idx = align_flows(ts, pairs, values=vals, **align_kw)
    placed = sorted(((i, a) for (_, a), i in zip(pairs, idx) if i is not None), key=lambda x: x[0])
    out = []
    for i, (t, v) in enumerate(zip(ts, vals)):
        active = [(ts[j], a) for j, a in placed if j <= i]
        cum = sum(a for _, a in active)
        raw = v - base
        md = modified_dietz(base, v, active, t0, t) if base > 0 else None
        out.append({
            "cumulative_flows": round(cum, 2),
            "net_gain_loss": round(raw - cum, 2),
            "net_gain_loss_raw": round(raw, 2),
            "net_percentage_gain": round(md * 100.0, 4) if md is not None else 0.0,
            "net_percentage_gain_raw": round(raw / base * 100.0, 4) if base else 0.0,
            "flows": [a for j, a in placed if j == i],
        })
    return out
