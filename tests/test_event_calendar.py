"""event_calendar: sessions math, FOMC / CPI / jobs windows, the event-risk score, the prompt block,
snapshots (SQLite) and the dashboard payload — no network (earnings lookups are stubbed)."""
from __future__ import annotations

from datetime import date, datetime, time

import pytest
import pytz
from sqlalchemy import create_engine, text

import event_calendar as ec

ET = pytz.timezone("US/Eastern")


def _et(y, m, d, hh=9, mm=45):
    return ET.localize(datetime(y, m, d, hh, mm))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setenv("DAI_EARNINGS_LOOKUP", "0")
    monkeypatch.delenv("DAI_EVENT_CALENDAR_FILE", raising=False)
    ec._EARN_CACHE.clear()
    yield
    ec._EARN_CACHE.clear()


# ----------------------------------------------------------------------------- sessions
def test_sessions_skip_weekends_and_holidays():
    assert ec.sessions_between(date(2026, 9, 14), date(2026, 9, 16)) == 2
    assert ec.sessions_between(date(2026, 9, 4), date(2026, 9, 8)) == 1          # Labor Day Sep 7
    assert ec.sessions_between(date(2026, 9, 16), date(2026, 9, 14)) == -2
    assert ec.sessions_between(date(2026, 9, 14), date(2026, 9, 14)) == 0
    assert ec.add_sessions(date(2026, 9, 11), 3) == date(2026, 9, 16)              # Fri → Mon, Tue, Wed
    assert ec.add_sessions(date(2026, 7, 2), 1) == date(2026, 7, 6)                # Jul 3 closed
    assert not ec.is_session(date(2026, 11, 26)) and ec.is_session(date(2026, 11, 27))


def test_session_state():
    assert ec.session_state(_et(2026, 9, 14, 9, 45)) == "session open"
    assert ec.session_state(_et(2026, 9, 14, 8, 0)) == "pre-market"
    assert ec.session_state(_et(2026, 9, 14, 17, 0)) == "after hours"
    assert ec.session_state(_et(2026, 9, 12, 12, 0)) == "weekend/holiday"


# ----------------------------------------------------------------------------- macro windows
def test_fomc_window_two_sessions_and_two_pm_cutover():
    s = ec.macro_statuses(date(2026, 9, 14))["fomc"]
    assert s["next"] == "2026-09-16" and s["sessions_to"] == 2 and s["in_window"]
    s = ec.macro_statuses(date(2026, 9, 11))["fomc"]
    assert s["sessions_to"] == 3 and not s["in_window"]
    pre = ec.macro_statuses(date(2026, 9, 16), time(13, 0))["fomc"]
    assert pre["sessions_to"] == 0 and pre["phase"] == "pre" and pre["in_window"]
    post = ec.macro_statuses(date(2026, 9, 16), time(15, 0))["fomc"]
    assert post["next"] == "2026-10-28" and post["last"] == "2026-09-16" and post["just_printed"] and not post["in_window"]
    after = ec.macro_statuses(date(2026, 9, 17))["fomc"]
    assert after["sessions_since"] == 1 and after["just_printed"]
    later = ec.macro_statuses(date(2026, 9, 18))["fomc"]
    assert not later["just_printed"]


def test_print_window_is_the_session_before_and_release_day_is_post():
    cpi = ec.macro_statuses(date(2026, 9, 10))["cpi"]          # CPI Fri Sep 11
    assert cpi["sessions_to"] == 1 and cpi["in_window"]
    day_of = ec.macro_statuses(date(2026, 9, 11), time(10, 0))["cpi"]
    assert day_of["phase"] == "post" and day_of["just_printed"] and day_of["next"] == "2026-10-14"
    jobs = ec.macro_statuses(date(2026, 10, 1))["jobs"]        # jobs Fri Oct 2
    assert jobs["in_window"]
    win, reason = ec.macro_window(ec.macro_statuses(date(2026, 9, 14)))
    assert win and "FOMC decision" in reason and "2 sessions" in reason
    assert not ec.macro_window(ec.macro_statuses(date(2026, 9, 23)))[0]


def test_calendar_file_adds_events(tmp_path, monkeypatch):
    f = tmp_path / "cal.json"
    f.write_text('{"other": [{"date": "2026-09-22", "label": "tariff deadline"}], "holidays": ["2026-09-23"]}')
    monkeypatch.setenv("DAI_EVENT_CALENDAR_FILE", str(f))
    ec._CACHE_FILE.update({"path": None, "mtime": None, "data": {}})
    assert not ec.is_session(date(2026, 9, 23))
    st = ec.macro_statuses(date(2026, 9, 21))
    assert st["other"] and st["other"][0]["label"] == "tariff deadline" and st["other"][0]["in_window"]
    ec._CACHE_FILE.update({"path": None, "mtime": None, "data": {}})


# ----------------------------------------------------------------------------- score
def test_score_is_deterministic_and_capped():
    st = ec.macro_statuses(date(2026, 9, 14))
    score, level, parts = ec.score_event_risk("RISK-OFF", st, [])
    assert score == 55 + 20 and level == "EXTREME"                       # RISK-OFF base + FOMC in 2 sessions
    assert [p[0] for p in parts] == ["regime", "fomc"]
    quiet = ec.macro_statuses(date(2026, 9, 23))
    assert ec.score_event_risk("RISK-ON", quiet, [])[0] == 10
    assert ec.score_event_risk(None, quiet, [])[0] == 30
    loaded = [{"flag": "reports_within_2"}] * 5 + [{"flag": "reports_within_5"}] * 3
    s, lvl, prt = ec.score_event_risk("RISK-OFF", st, loaded)
    assert s == 100 and lvl == "EXTREME"
    assert dict((p[0], p[2]) for p in prt if p[0] == "earnings" and "2 sessions" in p[1])["earnings"] == 40


def test_earnings_flags():
    assert ec._earnings_flag(0) == "reports_within_2" and ec._earnings_flag(2) == "reports_within_2"
    assert ec._earnings_flag(3) == "reports_within_5" and ec._earnings_flag(5) == "reports_within_5"
    assert ec._earnings_flag(6) is None and ec._earnings_flag(None) is None and ec._earnings_flag(-1) is None


# ----------------------------------------------------------------------------- context + block
def _stub_earnings(monkeypatch, table):
    def fake(ticker, *, today=None, engine=None, lookup=True):
        d = table.get(ticker)
        return {"ticker": ticker, "date": d.isoformat() if d else None, "estimate": False,
                "sessions_to": ec.sessions_between(today, d) if d else None, "source": "stub"}
    monkeypatch.setattr(ec, "next_earnings_date", fake)


def test_build_event_context_and_block(monkeypatch):
    _stub_earnings(monkeypatch, {"TSLA": date(2026, 10, 21), "MRK": date(2026, 9, 15), "GD": None})
    ctx = ec.build_event_context(holdings=["TSLA", "MRK", "CASH"], watchlist=["GD", "MRK"], regime="risk-off",
                                 now_et=_et(2026, 9, 14, 10, 25))
    assert ctx["today"] == "2026-09-14" and ctx["weekday"] == "Mon" and ctx["time_et"] == "10:25"
    assert ctx["regime"] == "RISK-OFF" and ctx["macro_window"] and ctx["risk_score"] == 55 + 20 + 20
    hold = {h["ticker"]: h for h in ctx["holdings_earnings"]}
    assert set(hold) == {"TSLA", "MRK"} and hold["MRK"]["flag"] == "reports_within_2" and hold["TSLA"]["flag"] is None
    assert [w["ticker"] for w in ctx["watchlist_earnings"]] == ["GD"]        # MRK already listed under holdings
    block = ctx["block"]
    assert block.startswith(ec.EVENT_CALENDAR_HEADER)
    assert "# TODAY: Mon 2026-09-14 10:25 ET (session open) | event-risk score 95/100 (EXTREME) | MACRO WINDOW: YES — FOMC decision Wed 2026-09-16 (in 2 sessions)" in block
    assert "# MACRO: FOMC decision Wed 2026-09-16 (in 2 sessions) 2:00 pm ET · CPI Wed 2026-10-14 (in 22 sessions) · jobs report Fri 2026-10-02 (in 14 sessions) · recent: CPI 2026-09-11 (1 session ago)" in block
    assert "MRK 2026-09-15 (1 sessions) ⚠ REPORTS ≤2 SESSIONS" in block and "TSLA 2026-10-21 (27 sessions)" in block
    assert "not_shown: GD" in block
    assert "at most 1 half-size BUY with D ≤2%" in block and "MRK 2026-09-15 → SELL before the print" in block
    assert ec.format_event_calendar(None) == ""


def test_quiet_day_block_falls_through_to_regime(monkeypatch):
    _stub_earnings(monkeypatch, {})
    ctx = ec.build_event_context(holdings=[], watchlist=[], regime="RISK-ON", now_et=_et(2026, 9, 23, 10, 0))
    assert not ctx["macro_window"] and ctx["risk_score"] == 10 and ctx["risk_level"] == "LOW"
    assert "MACRO WINDOW: no" in ctx["block"] and "up to 3 new BUYs at full rails" in ctx["block"]
    assert "EARNINGS (holdings): none in play" in ctx["block"]


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("DAI_EVENT_CALENDAR_ENABLED", "0")
    assert ec.build_event_context(holdings=["TSLA"], now_et=_et(2026, 9, 14)) is None


# ----------------------------------------------------------------------------- snapshots + payload (SQLite)
@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text("""CREATE TABLE trade_outcomes (id INTEGER PRIMARY KEY, config_hash TEXT, ticker TEXT,
            sell_timestamp TIMESTAMP, gain_loss_percentage REAL, original_reason TEXT)"""))
        conn.execute(text("""INSERT INTO trade_outcomes (config_hash, ticker, sell_timestamp, gain_loss_percentage, original_reason)
            VALUES ('cfg', 'MDB', '2026-09-02 13:36:00', -0.152, 'R1 pullback'), ('cfg', 'N/A', '2026-09-03 10:00:00', 0, 'x')"""))
    yield eng
    eng.dispose()


def test_snapshot_roundtrip_and_payload(engine, monkeypatch):
    _stub_earnings(monkeypatch, {"TSLA": date(2026, 9, 15)})
    ctx = ec.build_event_context(holdings=["TSLA"], regime="MIXED", now_et=_et(2026, 9, 14, 9, 25), engine=engine)
    rid = ec.record_snapshot(engine, "cfg", "20260914T092500", ctx)
    assert rid == 1
    latest = ec.latest_snapshot(engine, "cfg")
    assert latest["risk_score"] == ctx["risk_score"] and latest["regime"] == "MIXED" and latest["macro_window"]
    assert latest["holdings_earnings"][0]["ticker"] == "TSLA" and latest["fomc_date"] == "2026-09-16"
    assert ec.record_snapshot(engine, "cfg", None, None) is None

    payload = ec.event_risk_payload(engine, "cfg", 15, lambda d: "RISK-OFF" if d >= date(2026, 9, 10) else "RISK-ON",
                                    holdings=["TSLA"], now_et=_et(2026, 9, 14, 9, 25), horizon_sessions=4)
    dates = [p["date"] for p in payload["series"]]
    assert dates[0] == "2026-08-31" and dates[-1] == "2026-09-14" and "2026-09-07" not in dates      # Labor Day
    today_pt = payload["series"][-1]
    assert today_pt["recorded"] and today_pt["score"] == ctx["risk_score"] and today_pt["regime"] == "MIXED"
    sep10 = next(p for p in payload["series"] if p["date"] == "2026-09-10")
    assert sep10["regime"] == "RISK-OFF" and sep10["score"] == 55 + 12 and not sep10["recorded"]   # CPI next session
    sep1 = next(p for p in payload["series"] if p["date"] == "2026-09-01")
    assert sep1["regime"] == "RISK-ON" and sep1["score"] == 10
    assert [p["date"] for p in payload["projection"]] == ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    assert payload["projection"][0]["macro_window"] and payload["projection"][1]["score"] == 30 + 35    # MIXED + FOMC day
    assert payload["projection"][3]["score"] == 30
    kinds = {(e["kind"], e["date"]) for e in payload["events"]}
    assert ("fomc", "2026-09-16") in kinds and ("cpi", "2026-09-11") in kinds and ("jobs", "2026-09-04") in kinds
    assert ("earnings", "2026-09-15") in kinds
    assert payload["trades"] == [{"date": "2026-09-02", "ticker": "MDB", "action": "sell", "pct": -15.2}]
    assert payload["snapshots_recorded"] == 1 and payload["live"]["risk_score"] == ctx["risk_score"]
    assert payload["live"]["regime"] == "MIXED"


def test_earnings_cache_prefers_db_then_memory(engine, monkeypatch):
    calls = []

    def fake_yf(ticker, today):
        calls.append(ticker)
        return date(2026, 10, 21), False
    monkeypatch.setenv("DAI_EARNINGS_LOOKUP", "1")
    monkeypatch.setattr(ec, "_yf_next_earnings", fake_yf)
    a = ec.next_earnings_date("tsla", today=date(2026, 9, 14), engine=engine)
    assert a["ticker"] == "TSLA" and a["date"] == "2026-10-21" and a["sessions_to"] == 27 and a["source"] == "yfinance"
    ec._EARN_CACHE.clear()
    b = ec.next_earnings_date("TSLA", today=date(2026, 9, 14), engine=engine)      # served from earnings_calendar
    assert b["date"] == "2026-10-21" and calls == ["TSLA"]
    c = ec.next_earnings_date("TSLA", today=date(2026, 9, 14), engine=engine)      # memory
    assert c["date"] == "2026-10-21" and calls == ["TSLA"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM earnings_calendar")).scalar() == 1
