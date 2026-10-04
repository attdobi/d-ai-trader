"""cash_flows.py: external transfers (Schwab + manual), dedupe, exclusion and flow-adjusted gains.

In-memory SQLite only (never the live DB). The live case the module exists for: the account moved
$700 on 2026-09-23 and $22.82 on 2026-09-25 into the account and the Dashboard read them as gains.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

import cash_flows as cf

CFG = "cfg_test"
OTHER = "cfg_other"

LEGACY_DDL = """
CREATE TABLE external_cash_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_hash TEXT NOT NULL,
    txn_key TEXT UNIQUE NOT NULL,
    flow_date DATE NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    description TEXT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _schwab_row(engine, key, day, amount, config_hash=CFG, desc="JOURNAL FRM 53822742"):
    """Insert exactly like benchmark_tracker.refresh_cash_flows (no source/excluded columns)."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO external_cash_flows (config_hash, txn_key, flow_date, amount, description)
            VALUES (:c, :k, :d, :a, :desc)
            ON CONFLICT DO NOTHING
        """), {"c": config_hash, "k": key, "d": day, "a": amount, "desc": desc})


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    cf.ensure_schema(eng)
    return eng


def _flow(fid, day, amount, source="schwab", excluded=False):
    return {"id": fid, "date": day, "amount": amount, "source": source, "excluded": excluded}


# ----------------------------------------------------------------------------- dedupe / exclusion
def test_manual_entry_matching_a_schwab_row_is_a_duplicate():
    flows = cf.mark_counted([
        _flow(1, date(2026, 9, 23), 700.0),
        _flow(2, date(2026, 9, 25), 700.0, source="manual"),      # 2 days later, same amount
        _flow(3, date(2026, 9, 25), 22.82, source="manual"),      # no Schwab twin
    ])
    by_id = {f["id"]: f for f in flows}
    assert by_id[1]["counted"] and by_id[1]["duplicate_of"] is None
    assert not by_id[2]["counted"] and by_id[2]["duplicate_of"] == 1
    assert by_id[3]["counted"]
    assert cf.net_flows(flows) == 722.82


def test_dedupe_window_tolerance_sign_and_one_to_one():
    flows = cf.mark_counted([
        _flow(1, date(2026, 9, 23), 700.0),
        _flow(2, date(2026, 9, 27), 700.0, source="manual"),      # 4 days: outside ±3
        _flow(3, date(2026, 9, 23), 700.02, source="manual"),     # 2 cents: outside ±$0.01
        _flow(4, date(2026, 9, 23), -700.0, source="manual"),     # opposite sign
        _flow(5, date(2026, 9, 22), 700.01, source="manual"),     # within ±$0.01 → duplicate of #1
        _flow(6, date(2026, 9, 23), 700.0, source="manual"),      # #1 already claimed → counts
    ])
    by_id = {f["id"]: f for f in flows}
    assert by_id[5]["duplicate_of"] == 1 and not by_id[5]["counted"]
    for fid in (2, 3, 4, 6):
        assert by_id[fid]["counted"] and by_id[fid]["duplicate_of"] is None, fid


def test_excluded_schwab_row_does_not_count_and_does_not_absorb_a_manual_entry():
    flows = cf.mark_counted([
        _flow(1, date(2026, 9, 23), 700.0, excluded=True),
        _flow(2, date(2026, 9, 23), 700.0, source="manual"),
    ])
    by_id = {f["id"]: f for f in flows}
    assert not by_id[1]["counted"]
    assert by_id[2]["counted"] and by_id[2]["duplicate_of"] is None
    assert cf.net_flows(flows) == 700.0
    totals = cf.flow_totals(flows)
    assert totals["excluded"] == 1 and totals["count"] == 1 and totals["net"] == 700.0


# ----------------------------------------------------------------------------- DB round trip
def test_add_list_exclude_delete_round_trip(engine):
    _schwab_row(engine, "131462110360", "2026-09-23", 700.0)
    _schwab_row(engine, "131720324255", "2026-09-25", 22.82)
    _schwab_row(engine, "999", "2026-09-24", 5000.0, config_hash=OTHER)

    flows = cf.list_flows(engine, CFG)
    assert [(f["date"], f["amount"], f["source"], f["excluded"]) for f in flows] == [
        (date(2026, 9, 23), 700.0, "schwab", False), (date(2026, 9, 25), 22.82, "schwab", False)]

    dup = cf.add_manual_flow(engine, CFG, "2026-09-24", "700", "deposit", note="moved from checking",
                             today=date(2026, 10, 4))
    assert dup["source"] == "manual" and dup["txn_key"].startswith("manual:")
    assert dup["duplicate_of"] == flows[0]["id"] and not dup["counted"]
    wd = cf.add_manual_flow(engine, CFG, date(2026, 10, 1), 100, "withdrawal", today=date(2026, 10, 4))
    assert wd["amount"] == -100.0 and wd["counted"] and wd["description"] == "Manual withdrawal"
    assert cf.net_flows(cf.list_flows(engine, CFG)) == 622.82

    # Exclude the $22.82 Schwab row, then include it again.
    ex = cf.set_excluded(engine, CFG, flows[1]["id"], True)
    assert ex["excluded"] and not ex["counted"]
    assert cf.net_flows(cf.list_flows(engine, CFG)) == 600.0
    assert not cf.set_excluded(engine, CFG, flows[1]["id"], False)["excluded"]

    # Manual rows are deleted, Schwab rows are excluded — never the other way round.
    with pytest.raises(cf.CashFlowError):
        cf.delete_manual_flow(engine, CFG, flows[0]["id"])
    with pytest.raises(cf.CashFlowError):
        cf.set_excluded(engine, CFG, wd["id"], True)
    cf.delete_manual_flow(engine, CFG, wd["id"])
    assert cf.net_flows(cf.list_flows(engine, CFG)) == 722.82

    # Scoped by config: another config's row is invisible and untouchable.
    other_id = cf.list_flows(engine, OTHER)[0]["id"]
    with pytest.raises(cf.NotFound):
        cf.set_excluded(engine, CFG, other_id, True)
    assert cf.list_flows(engine, OTHER)[0]["excluded"] is False


def test_list_flows_date_filter_keeps_duplicate_resolution(engine):
    _schwab_row(engine, "a", "2026-09-23", 700.0)
    cf.add_manual_flow(engine, CFG, "2026-09-25", 700, "deposit", today=date(2026, 10, 4))
    window = cf.list_flows(engine, CFG, start="2026-09-24")
    assert len(window) == 1 and window[0]["source"] == "manual" and window[0]["duplicate_of"] is not None
    assert cf.net_flows(window) == 0.0


@pytest.mark.parametrize("args, message", [
    (("2026-10-05", 10, "deposit"), "future"),
    (("2026/10/01", 10, "deposit"), "YYYY-MM-DD"),
    (("", 10, "deposit"), "required"),
    (("2026-10-01", 0, "deposit"), "greater than 0"),
    (("2026-10-01", -5, "deposit"), "greater than 0"),
    (("2026-10-01", "abc", "deposit"), "number"),
    (("2026-10-01", float("nan"), "deposit"), "greater than 0"),
    (("2026-10-01", 0.001, "deposit"), "at least"),
    (("2026-10-01", 10, "transfer"), "direction"),
    (("2026-10-01", 10, "deposit", "x" * 201), "200 characters"),
])
def test_manual_entry_validation(args, message):
    with pytest.raises(cf.CashFlowError) as exc:
        cf.validate_manual_flow(*args, today=date(2026, 10, 4))
    assert message in str(exc.value)


def test_manual_entry_validation_accepts_formatted_amounts():
    assert cf.validate_manual_flow("2026-10-04", "$1,234.567", "withdrawal", "  note  ",
                                   today=date(2026, 10, 4)) == (date(2026, 10, 4), -1234.57, "note")


def test_migration_adds_columns_to_a_legacy_table_and_reads_before_it():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text(LEGACY_DDL))
    _schwab_row(eng, "1", "2026-07-15", 1000.0)
    # Before the migration: the legacy read path (every row Schwab, nothing excluded).
    pre = cf.list_flows(eng, CFG)
    assert pre[0]["source"] == "schwab" and pre[0]["counted"]
    cf.ensure_schema(eng)
    cf.ensure_schema(eng)                                      # idempotent
    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(external_cash_flows)")).fetchall()}
        row = conn.execute(text("SELECT source, excluded, note FROM external_cash_flows")).fetchone()
    assert {"source", "note", "excluded"} <= cols
    assert row.source == "schwab" and not row.excluded and row.note is None


def test_init_database_migration_sql_is_idempotent_postgres_syntax():
    assert set(cf.ALTER_POSTGRES) == {"source", "note", "excluded"}
    assert all("ADD COLUMN IF NOT EXISTS" in sql for sql in cf.ALTER_POSTGRES.values())
    assert "CREATE TABLE IF NOT EXISTS external_cash_flows" in cf.DDL_POSTGRES
    assert "IF NOT EXISTS" in cf.DDL_INDEX


# ----------------------------------------------------------------------------- returns
def test_modified_dietz_weights_flows_by_time_invested():
    start, end = datetime(2026, 9, 1), datetime(2026, 9, 11)
    assert cf.modified_dietz(1000, 1100, [], start, end) == pytest.approx(0.10)
    # +$1,000 halfway: gain 100 on 1000 + 0.5*1000 average capital.
    assert cf.modified_dietz(1000, 2100, [(datetime(2026, 9, 6), 1000)], start, end) == pytest.approx(100 / 1500)
    # Deposit at the start weighs 1, at the end 0; a pre-start date clamps to 1.
    assert cf.modified_dietz(1000, 2100, [(date(2026, 9, 1), 1000)], start, end) == pytest.approx(100 / 2000)
    assert cf.modified_dietz(1000, 2100, [(datetime(2026, 9, 11), 1000)], start, end) == pytest.approx(0.10)
    assert cf.modified_dietz(1000, 2100, [(date(2026, 8, 1), 1000)], start, end) == pytest.approx(100 / 2000)
    # Withdrawal halfway: −$500 is not a loss.
    assert cf.modified_dietz(1000, 550, [(datetime(2026, 9, 6), -500)], start, end) == pytest.approx(50 / 750)
    # No capital base → undefined.
    assert cf.modified_dietz(0, 0, [], start, end) is None


def test_flow_adjusted_gain_live_september_case():
    """The live numbers of 2026-10-02: $1,474.63 baseline (2026-04-27), $3,217.15 now and $1,704.29 of
    net transfers since (incl. the $700 + $22.82 September journals) → a $38.23 gain, not $1,742.52."""
    flows = [(date(2026, 6, 23), -500), (date(2026, 6, 23), 124.32), (date(2026, 6, 24), 700),
             (date(2026, 6, 24), 115.18), (date(2026, 7, 15), 1000), (date(2026, 7, 21), -1853),
             (date(2026, 7, 22), 1394.97), (date(2026, 9, 23), 700), (date(2026, 9, 25), 22.82),
             (date(2026, 4, 1), 9999)]                         # before the baseline: ignored
    g = cf.flow_adjusted_gain(3217.15, 1474.63, flows, baseline_at=datetime(2026, 4, 27, 10, 51),
                              as_of=datetime(2026, 10, 2, 12, 33))
    assert g["net_gain_loss_raw"] == 1742.52
    assert g["net_flows"] == 1704.29 and g["flow_count"] == 9
    assert g["net_gain_loss"] == 38.23
    assert 0 < g["net_percentage_gain"] < 3 < g["net_percentage_gain_raw"]
    assert g["method"] == "modified_dietz" and g["baseline_date"] == "2026-04-27"


def test_flow_adjusted_gain_without_baseline_timestamp_uses_midpoint_dietz():
    g = cf.flow_adjusted_gain(11100, 10000, [(date(2026, 9, 1), 1000)])
    assert g["net_gain_loss"] == 100 and g["method"] == "dietz_midpoint"
    assert g["net_percentage_gain"] == pytest.approx(100 / 10500 * 100, abs=1e-4)


# ----------------------------------------------------------------------------- series
def test_cumulative_series_calendar_alignment():
    ts = [datetime(2026, 9, 22, 7), datetime(2026, 9, 23, 7), datetime(2026, 9, 24, 7), datetime(2026, 9, 26, 7)]
    flows = [(date(2026, 9, 23), 700.0), (date(2026, 9, 25), 22.82), (date(2026, 9, 30), 5.0)]
    assert cf.cumulative_flow_series(ts, flows) == [0.0, 700.0, 700.0, 722.82]  # 9/30: not visible yet


def test_settlement_lag_pins_the_flow_to_the_step_it_posted_in():
    # Withdrawal dated 7/21 posts on 7/22: calendar pinning would draw a +$1,853 gain for a day.
    ts = [datetime(2026, 7, 20, 7), datetime(2026, 7, 21, 7), datetime(2026, 7, 21, 13), datetime(2026, 7, 22, 7)]
    vals = [2400.0, 2405.0, 2410.0, 557.0]
    flows = [(date(2026, 7, 21), -1853.0)]
    assert cf.align_flows(ts, flows, values=vals) == [3]
    assert cf.cumulative_flow_series(ts, flows, values=vals) == [0.0, 0.0, 0.0, -1853.0]


def test_transfer_cluster_is_solved_jointly():
    # −$1,853 and +$1,394.97 posted together as one −$459.61 step, next to settled-cash artifacts.
    ts = [datetime(2026, 7, 20 + i // 2, 7 + 6 * (i % 2)) for i in range(8)]
    vals = [2820.0, 2821.0, 2361.4, 2362.0, 2092.0, 2362.5, 2363.0, 2364.0]
    flows = [(date(2026, 7, 21), -1853.0), (date(2026, 7, 22), 1394.97)]
    idx = cf.align_flows(ts, flows, values=vals)
    assert idx[0] == idx[1] == 2
    adj = [v - vals[0] - c for v, c in zip(vals, cf.cumulative_flow_series(ts, flows, values=vals))]
    assert max(abs(a) for a in adj[:4]) < 5


def test_adjusted_performance_series_strips_a_deposit():
    pts = [(datetime(2026, 9, 21, 7), 2480.0), (datetime(2026, 9, 22, 7), 2482.45),
           (datetime(2026, 9, 23, 8), 3163.79), (datetime(2026, 9, 24, 8), 3170.0)]
    rows = cf.adjusted_performance_series(pts, [(date(2026, 9, 23), 700.0)])
    assert rows[0]["net_gain_loss"] == 0 and rows[0]["cumulative_flows"] == 0
    assert rows[2]["flows"] == [700.0] and rows[2]["cumulative_flows"] == 700.0
    assert rows[2]["net_gain_loss_raw"] == pytest.approx(683.79)
    assert rows[2]["net_gain_loss"] == pytest.approx(-16.21)
    assert rows[3]["net_gain_loss"] == pytest.approx(-10.0)
    assert abs(rows[3]["net_percentage_gain"]) < 1 < rows[3]["net_percentage_gain_raw"]
    assert cf.adjusted_performance_series([], []) == []


def test_flow_label_and_serialization():
    assert cf.flow_label(700) == "+$700 deposit"
    assert cf.flow_label(22.82) == "+$22.82 deposit"
    assert cf.flow_label(-1853) == "−$1,853 withdrawal"
    out = cf.serialize_flow({"id": 1, "date": date(2026, 9, 23), "amount": 700.0, "recorded_at": None,
                             "counted": True}, baseline_date=date(2026, 9, 24))
    assert out["date"] == "2026-09-23" and out["label"] == "+$700 deposit"
    assert out["direction"] == "deposit" and out["in_gain_period"] is False


# ----------------------------------------------------------------------------- Schwab sync + TWR
class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_transactions(self, account_hash, start_date=None, end_date=None):
        self.calls.append(start_date)
        return _Resp(self.payload)


def _stub_schwab(monkeypatch, payload):
    import sys
    import types
    client = _Client(payload)
    stub = types.ModuleType("schwab_client")
    stub.schwab_client = types.SimpleNamespace(ensure_authenticated=lambda: True, client=client, account_hash="h")
    monkeypatch.setitem(sys.modules, "schwab_client", stub)
    return client


def test_schwab_sync_never_overwrites_excluded_or_manual_rows(engine, monkeypatch):
    import benchmark_tracker as bt
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE portfolio_history (timestamp TIMESTAMP, config_hash TEXT)"))
    _schwab_row(engine, "131462110360", "2026-09-23", 700.0)
    flows = cf.list_flows(engine, CFG)
    cf.set_excluded(engine, CFG, flows[0]["id"], True)
    manual = cf.add_manual_flow(engine, CFG, "2026-10-03", 50, "deposit", today=date(2026, 10, 4))

    client = _stub_schwab(monkeypatch, [
        {"type": "JOURNAL", "activityId": 131462110360, "netAmount": 700.0, "time": "2026-09-23T14:00:00+0000",
         "description": "JOURNAL FRM 53822742"},
        {"type": "JOURNAL", "activityId": 131720324255, "netAmount": 22.82, "time": "2026-09-25T14:00:00+0000",
         "description": "JOURNAL FRM 53822742"},
        {"type": "TRADE", "activityId": 1, "netAmount": -300.0, "time": "2026-09-26T14:00:00+0000"},
    ])
    status = bt.refresh_cash_flows(engine, CFG, force=True)
    assert status["status"] == "ok" and status["fetched"] == 2 and status["inserted"] == 1
    # Resume window: from the newest SCHWAB row (9/23) minus 7 days — not from the 10/03 manual entry.
    assert client.calls[0] == datetime(2026, 9, 16)

    after = {f["txn_key"]: f for f in cf.list_flows(engine, CFG)}
    assert after["131462110360"]["excluded"] is True
    assert after[manual["txn_key"]]["source"] == "manual" and after[manual["txn_key"]]["amount"] == 50.0
    assert after["131720324255"]["source"] == "schwab" and after["131720324255"]["counted"]
    assert cf.net_flows(list(after.values())) == 72.82


def test_schwab_sync_unavailable_and_ttl(engine, monkeypatch):
    import sys
    import types
    import benchmark_tracker as bt
    stub = types.ModuleType("schwab_client")
    stub.schwab_client = types.SimpleNamespace(ensure_authenticated=lambda: False, client=None)
    monkeypatch.setitem(sys.modules, "schwab_client", stub)
    assert bt.refresh_cash_flows(engine, CFG, force=True)["status"] == "unavailable"
    assert bt.refresh_cash_flows(engine, CFG)["status"] == "skipped"           # inside the TTL


def test_twr_uses_counted_flows_only(monkeypatch):
    """get_benchmark_performance strips Schwab + manual transfers once each and ignores excluded rows."""
    import sqlite3
    import time as _time
    import benchmark_tracker as bt

    eng = create_engine("sqlite://", connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})
    bt.ensure_tables(eng)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE portfolio_history (timestamp TIMESTAMP, total_portfolio_value REAL, config_hash TEXT)"))
        conn.execute(text("CREATE TABLE trade_outcomes (gain_loss_amount REAL, gain_loss_percentage REAL, config_hash TEXT, sell_timestamp TIMESTAMP)"))
        conn.execute(text("CREATE TABLE model_transitions (model_name TEXT, started_at TIMESTAMP, config_hash TEXT)"))
    today = datetime.utcnow().date()
    days = [today - timedelta(days=9 - i) for i in range(10)]
    values = [1000.0, 1001.0, 1002.0, 1703.0, 1704.0, 1705.0, 1706.0, 1707.0, 1708.0, 1709.0]   # +$700 on day 3
    with eng.begin() as conn:
        for d, v in zip(days, values):
            conn.execute(text("INSERT INTO portfolio_history VALUES (:t, :v, :c)"),
                         {"t": datetime.combine(d, datetime.min.time()) + timedelta(hours=12), "v": v, "c": CFG})
            for sym in [b["symbol"] for b in bt.BENCHMARKS]:
                conn.execute(text("INSERT INTO benchmark_history (symbol, date, close) VALUES (:s, :d, 100)"),
                             {"s": sym, "d": d})
    _schwab_row(eng, "dep", days[3].isoformat(), 700.0)
    _schwab_row(eng, "bogus", days[6].isoformat(), -400.0)          # not a real transfer: excluded below
    cf.set_excluded(eng, CFG, [f for f in cf.list_flows(eng, CFG) if f["txn_key"] == "bogus"][0]["id"], True)
    cf.add_manual_flow(eng, CFG, days[4].isoformat(), 700, "deposit", today=today)   # duplicate of "dep"

    monkeypatch.setattr(bt, "_last_refresh", {"benchmarks": _time.time(), "flows": _time.time()})
    synced = []
    real_refresh = bt.refresh_cash_flows
    monkeypatch.setattr(bt, "refresh_cash_flows", lambda e, h, force=False: synced.append(h) or real_refresh(e, h, force))
    # A simulation dashboard passes sync_flows=False: its config never ingests the real account's transfers.
    assert "error" not in bt.get_benchmark_performance(eng, CFG, days=30, sync_flows=False) and synced == []
    out = bt.get_benchmark_performance(eng, CFG, days=30)
    assert synced == [CFG]
    assert "error" not in out, out
    # Flowless growth only: 1000 → 1002 then 1003 → 1709 less the $700 → about +0.9%, not +71% / +40%.
    assert 0.5 < out["stats"]["portfolio"]["return_pct"] < 1.5
    flows = out["stats"]["external_flows"]
    assert [(f["amount"], f["source"], f["label"]) for f in flows] == [(700.0, "schwab", "+$700 deposit")]


# ----------------------------------------------------------------------------- txn_key unique per config
def test_same_schwab_transfer_syncs_into_each_config(engine, monkeypatch):
    """The read-only live view (or any other config) syncing a transfer first must not hide it from the
    trading config: the key is unique per config, so each config gets its own row."""
    import benchmark_tracker as bt
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE portfolio_history (timestamp TIMESTAMP, config_hash TEXT)"))
    _stub_schwab(monkeypatch, [{"type": "JOURNAL", "activityId": 131462110360, "netAmount": 700.0,
                                "time": "2026-09-23T14:00:00+0000", "description": "JOURNAL FRM 53822742"}])
    assert bt.refresh_cash_flows(engine, "SCHWAB_LIVE_VIEW", force=True)["inserted"] == 1
    assert bt.refresh_cash_flows(engine, CFG, force=True)["inserted"] == 1
    assert bt.refresh_cash_flows(engine, CFG, force=True)["inserted"] == 0        # same config: no duplicate
    for cfg in ("SCHWAB_LIVE_VIEW", CFG):
        assert [(f["txn_key"], f["amount"]) for f in cf.list_flows(engine, cfg)] == [("131462110360", 700.0)]
    g = cf.flow_adjusted_gain(10700, 10000, cf.counted_pairs(cf.list_flows(engine, CFG)),
                              baseline_at=datetime(2026, 9, 1), as_of=datetime(2026, 10, 1))
    assert g["net_flows"] == 700.0 and g["net_gain_loss"] == 0.0                  # the deposit is not profit
    # Manual rows: the id lookup after the insert is scoped by config too.
    m = cf.add_manual_flow(engine, OTHER, "2026-09-30", 5, "deposit", today=date(2026, 10, 4))
    assert m["source"] == "manual" and cf.list_flows(engine, OTHER)[0]["id"] == m["id"]


class _FakePgConn:
    """Records the SQL migrate_unique_key issues on a 'postgresql' connection (no database)."""
    dialect = type("D", (), {"name": "postgresql"})()

    def __init__(self, index=False, legacy=True, fail_on=None):
        self.index, self.legacy, self.fail_on, self.log = index, legacy, fail_on, []

    def begin_nested(self):
        conn = self

        class _Savepoint:
            def __enter__(self):
                conn.log.append("SAVEPOINT")

            def __exit__(self, exc_type, exc, tb):
                conn.log.append("ROLLBACK TO SAVEPOINT" if exc_type else "RELEASE SAVEPOINT")
                return False
        return _Savepoint()

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split())
        self.log.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("must be owner of table external_cash_flows")
        if "pg_constraint" in sql:
            value = 1 if self.legacy else None
        elif "to_regclass(:n)" in sql:
            value = cf.UNIQUE_INDEX if self.index else None
        elif "to_regclass('external_cash_flows')" in sql:
            value = "external_cash_flows"
        else:
            value = None
        return type("R", (), {"scalar": staticmethod(lambda: value)})()


def test_migrate_unique_key_creates_the_composite_index_before_dropping_the_old_key():
    assert "txn_key TEXT UNIQUE" not in cf.DDL_POSTGRES and "UNIQUE (config_hash, txn_key)" in cf.DDL_POSTGRES
    assert "IF NOT EXISTS" in cf.DDL_UNIQUE_INDEX and "(config_hash, txn_key)" in cf.DDL_UNIQUE_INDEX
    assert "DROP CONSTRAINT IF EXISTS external_cash_flows_txn_key_key" in cf.DROP_LEGACY_UNIQUE

    conn = _FakePgConn()
    assert cf.migrate_unique_key(conn) == "migrated"
    ddl = [s for s in conn.log if s.startswith(("LOCK", "CREATE", "ALTER"))]
    assert ddl == [cf.LOCK_FOR_MIGRATION, cf.DDL_UNIQUE_INDEX, cf.DROP_LEGACY_UNIQUE]
    assert conn.log[0] == "SAVEPOINT" and conn.log[-1] == "RELEASE SAVEPOINT"

    # The DROP fails (not the owner): the savepoint rolls the new index back with it, the old
    # table-wide key stays in force, and nothing is raised into the caller's transaction.
    conn = _FakePgConn(fail_on="DROP CONSTRAINT")
    assert cf.migrate_unique_key(conn).startswith("failed:")
    assert conn.log[-1] == "ROLLBACK TO SAVEPOINT" and cf.DDL_UNIQUE_INDEX in conn.log

    # Already migrated: no DDL, no lock.
    conn = _FakePgConn(index=True, legacy=False)
    assert cf.migrate_unique_key(conn) == "current"
    assert not [s for s in conn.log if s.startswith(("LOCK", "CREATE", "ALTER"))]

    eng = create_engine("sqlite://")
    with eng.begin() as sqlite_conn:
        assert cf.migrate_unique_key(sqlite_conn) == "skipped"


def test_migrate_unique_key_on_a_real_postgres():
    """Opt-in (DAI_TEST_PG_URL, a scratch database): legacy table → per-config key, idempotent,
    concurrent-safe. Runs in its own schema, which it drops."""
    import os
    import threading
    url = os.environ.get("DAI_TEST_PG_URL")
    if not url:
        pytest.skip("set DAI_TEST_PG_URL to a scratch Postgres database")
    schema = f"cf_test_{os.getpid()}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engines = []

    def scoped():
        e = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        engines.append(e)
        return e

    try:
        eng = scoped()
        with eng.begin() as conn:
            conn.execute(text(LEGACY_DDL.replace("AUTOINCREMENT", "").replace("id INTEGER PRIMARY KEY", "id SERIAL PRIMARY KEY")))
        _schwab_row(eng, "131462110360", "2026-09-23", 700.0, config_hash="SCHWAB_LIVE_VIEW")
        _schwab_row(eng, "131462110360", "2026-09-23", 700.0)                      # blocked by the old key
        assert cf.list_flows(eng, CFG) == []

        out = []                                                                   # dashboard vs init_database
        a, b = scoped(), scoped()
        barrier = threading.Barrier(2)

        def dashboard():
            barrier.wait()
            cf.ensure_schema(a)
            out.append("dashboard")

        def init_db():
            barrier.wait()
            with b.begin() as conn:
                out.append(cf.migrate_unique_key(conn))

        threads = [threading.Thread(target=dashboard), threading.Thread(target=init_db)]
        [t.start() for t in threads]
        [t.join(60) for t in threads]
        assert sorted(out)[0] == "dashboard" and not any(str(o).startswith("failed") for o in out), out
        with eng.begin() as conn:
            assert cf.migrate_unique_key(conn) == "current"
            uniques = conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = to_regclass('external_cash_flows') AND contype = 'u'"
            )).fetchall()
        assert uniques == []                                                       # the table-wide key is gone
        _schwab_row(eng, "131462110360", "2026-09-23", 700.0)
        _schwab_row(eng, "131462110360", "2026-09-23", 700.0)
        assert [f["amount"] for f in cf.list_flows(eng, CFG)] == [700.0]           # once per config
    finally:
        for e in engines:
            e.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


# ----------------------------------------------------------------------------- baseline-day transfers
# A +$1,000 deposit dated 2026-05-04, the day of the first snapshot / baseline (10:00). Dates carry no
# time of day, so only the values say whether it was already inside the 10:00 value.
EMBEDDED_PTS = [(datetime(2026, 5, 4, 10), 2000.0), (datetime(2026, 5, 4, 12), 2010.0),
                (datetime(2026, 5, 5, 8), 1980.0), (datetime(2026, 5, 5, 12), 1995.0), (datetime(2026, 5, 6, 8), 2005.0)]
POSTED_AFTER_PTS = [(datetime(2026, 5, 4, 10), 2000.0), (datetime(2026, 5, 4, 12), 3010.0),
                    (datetime(2026, 5, 5, 8), 2980.0), (datetime(2026, 5, 5, 12), 2995.0), (datetime(2026, 5, 6, 8), 3005.0)]
DAY0_DEPOSIT = [(date(2026, 5, 4), 1000.0)]


def _headline(points, flows, current=None):
    base_at, base = points[0]
    cur_at, cur = current or points[-1]
    keep = cf.baseline_embedded(flows, base, base_at, points[1:], current=(cur_at, cur))
    return cf.flow_adjusted_gain(cur, base, [p for k, p in enumerate(flows) if k not in keep],
                                 baseline_at=base_at, as_of=cur_at), keep


def test_baseline_day_deposit_already_in_the_first_point_is_not_subtracted():
    # Chart: no value step explains +$1,000, so it is part of the first value — no fake −$1,000 step.
    assert cf.align_flows([p[0] for p in EMBEDDED_PTS], DAY0_DEPOSIT, values=[p[1] for p in EMBEDDED_PTS]) == [None]
    rows = cf.adjusted_performance_series(EMBEDDED_PTS, DAY0_DEPOSIT)
    assert [r["cumulative_flows"] for r in rows] == [0.0] * 5 and not any(r["flows"] for r in rows)
    assert rows[-1]["net_gain_loss"] == pytest.approx(5.0) and rows[-1]["net_percentage_gain"] == pytest.approx(0.25)
    # Headline: the same evidence, the same answer (+$5, +0.25%), not −$995 / −33%.
    g, embedded = _headline(EMBEDDED_PTS, DAY0_DEPOSIT)
    assert embedded == {0}
    assert g["net_gain_loss"] == pytest.approx(5.0) and g["net_flows"] == 0 and g["flow_count"] == 0
    assert g["net_percentage_gain"] == pytest.approx(0.25)
    # One point only: nothing to test against, and point 0 is the base — the chart shows no step either.
    one = cf.adjusted_performance_series(EMBEDDED_PTS[:1], DAY0_DEPOSIT)
    assert one[0]["net_gain_loss"] == 0 and one[0]["cumulative_flows"] == 0


def test_baseline_day_deposit_that_posts_after_the_first_point_is_still_subtracted():
    assert cf.align_flows([p[0] for p in POSTED_AFTER_PTS], DAY0_DEPOSIT, values=[p[1] for p in POSTED_AFTER_PTS]) == [1]
    rows = cf.adjusted_performance_series(POSTED_AFTER_PTS, DAY0_DEPOSIT)
    assert rows[1]["flows"] == [1000.0] and rows[-1]["net_gain_loss"] == pytest.approx(5.0)
    g, embedded = _headline(POSTED_AFTER_PTS, DAY0_DEPOSIT)
    assert embedded == set() and g["net_flows"] == 1000.0 and g["net_gain_loss"] == pytest.approx(5.0)
    # Before any snapshot after the baseline, the live value is the evidence.
    g, embedded = _headline(POSTED_AFTER_PTS[:1], DAY0_DEPOSIT, current=(datetime(2026, 5, 4, 15), 3004.0))
    assert embedded == set() and g["net_gain_loss"] == pytest.approx(4.0)
    g, embedded = _headline(POSTED_AFTER_PTS[:1], DAY0_DEPOSIT, current=(datetime(2026, 5, 4, 15), 2004.0))
    assert embedded == {0} and g["net_gain_loss"] == pytest.approx(4.0)
    # No evidence at all (no later point, the live value is weeks later): subtracted, as before.
    assert cf.baseline_embedded(DAY0_DEPOSIT, 2000.0, datetime(2026, 5, 4, 10), [],
                                current=(datetime(2026, 6, 4), 2004.0)) == set()


def test_in_baseline_ids_reads_this_configs_snapshots(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE portfolio_history (timestamp TIMESTAMP, total_portfolio_value REAL, config_hash TEXT)"))
        for (ts, v), cfg in [(p, CFG) for p in EMBEDDED_PTS[1:]] + [((datetime(2026, 5, 4, 12), 3010.0), OTHER)]:
            conn.execute(text("INSERT INTO portfolio_history VALUES (:t, :v, :c)"), {"t": ts, "v": v, "c": cfg})
    _schwab_row(engine, "dep", "2026-05-04", 1000.0)
    _schwab_row(engine, "later", "2026-05-20", 50.0)
    flows = cf.list_flows(engine, CFG)
    dep_id = [f["id"] for f in flows if f["txn_key"] == "dep"][0]
    base_at = datetime(2026, 5, 4, 10)
    assert cf.in_baseline_ids(engine, CFG, flows, 2000.0, base_at) == {dep_id}
    assert cf.baseline_snapshots(engine, CFG, base_at) and len(cf.baseline_snapshots(engine, CFG, base_at)) == 4
    # Another baseline day: nothing dated on it, nothing queried or dropped.
    assert cf.in_baseline_ids(engine, CFG, flows, 2000.0, datetime(2026, 5, 3, 10)) == set()
    # No portfolio_history table: no evidence, the transfer keeps being subtracted.
    bare = create_engine("sqlite://")
    cf.ensure_schema(bare)
    _schwab_row(bare, "dep", "2026-05-04", 1000.0)
    assert cf.in_baseline_ids(bare, CFG, cf.list_flows(bare, CFG), 2000.0, base_at) == set()
