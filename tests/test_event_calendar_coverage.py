"""event_calendar coverage: the built-in CPI / jobs calendars stop at 2026 (BLS had not published 2027).
When the next 45 days run past the last known date, the EVENT CALENDAR block, the dashboard payload
and the log (once a day) carry one CALENDAR GAP line. No date is ever invented."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

import pytest
import pytz
from sqlalchemy import create_engine

import event_calendar as ec

ET = pytz.timezone("US/Eastern")


def _et(y, m, d, hh=9, mm=45):
    return ET.localize(datetime(y, m, d, hh, mm))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("DAI_EARNINGS_LOOKUP", "0")
    monkeypatch.delenv("DAI_EVENT_CALENDAR_FILE", raising=False)
    monkeypatch.delenv("DAI_EVENT_CALENDAR_ENABLED", raising=False)
    ec._CACHE_FILE.update({"path": None, "mtime": None, "data": {}})
    ec._GAP_LOGGED["day"] = None
    yield
    ec._CACHE_FILE.update({"path": None, "mtime": None, "data": {}})
    ec._GAP_LOGGED["day"] = None


def test_no_gap_while_both_calendars_reach_45_days_out():
    cov = ec.calendar_coverage(date(2026, 10, 4))
    assert cov == {"horizon_end": "2026-11-18", "gaps": [], "warning": None}
    assert ec.calendar_coverage(date(2026, 10, 20))["warning"] is None       # horizon 12-04 = last jobs date


def test_gap_names_the_calendar_that_runs_out_first():
    cov = ec.calendar_coverage(date(2026, 10, 21))                            # horizon 12-05 > jobs 12-04
    assert [g["kind"] for g in cov["gaps"]] == ["jobs"]
    assert cov["warning"] == "CALENDAR GAP: no jobs dates after 2026-12-04 — add them via DAI_EVENT_CALENDAR_FILE"


def test_gap_for_both_uses_the_later_last_date():
    cov = ec.calendar_coverage(date(2026, 11, 2))
    assert [(g["kind"], g["last"]) for g in cov["gaps"]] == [("cpi", "2026-12-10"), ("jobs", "2026-12-04")]
    assert cov["warning"] == "CALENDAR GAP: no CPI or jobs dates after 2026-12-10 — add them via DAI_EVENT_CALENDAR_FILE"


def test_operator_file_closes_the_gap_and_no_dates_are_invented(tmp_path, monkeypatch):
    # placeholder test dates (not a real BLS schedule) — the file is the only way dates get added
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"cpi": ["2027-01-13", "2027-02-10"], "jobs": ["2027-01-08", "2027-02-05"]}))
    monkeypatch.setenv("DAI_EVENT_CALENDAR_FILE", str(f))
    assert ec.calendar_coverage(date(2026, 11, 2))["warning"] is None
    assert max(d for ys in ec.CPI_RELEASE_DATES.values() for d in ys) == "2026-12-10"
    assert max(d for ys in ec.JOBS_REPORT_DATES.values() for d in ys) == "2026-12-04"
    assert set(ec.CPI_RELEASE_DATES) == {2026} and set(ec.JOBS_REPORT_DATES) == {2026}


def test_block_carries_one_gap_line_right_under_macro():
    ctx = ec.build_event_context(holdings=[], regime="MIXED", now_et=_et(2026, 11, 2), lookup_earnings=False)
    lines = ctx["block"].splitlines()
    assert lines[2].startswith("# MACRO: ")
    assert lines[3] == ("# CALENDAR GAP: no CPI or jobs dates after 2026-12-10 — add them via DAI_EVENT_CALENDAR_FILE "
                        "(not_in_calendar = date unknown, not no print)")
    assert sum("CALENDAR GAP" in ln for ln in lines) == 1
    assert ctx["calendar_gap"]["warning"].startswith("CALENDAR GAP: no CPI or jobs dates")


def test_block_unchanged_without_a_gap():
    ctx = ec.build_event_context(holdings=[], regime="MIXED", now_et=_et(2026, 10, 5), lookup_earnings=False)
    assert "CALENDAR GAP" not in ctx["block"]
    assert len(ctx["block"].splitlines()) == 6
    assert ctx["block"].splitlines()[0] == ec.EVENT_CALENDAR_HEADER


def test_gap_is_logged_once_per_day(caplog):
    with caplog.at_level(logging.WARNING, logger="event_calendar"):
        for hh in (9, 12, 15):
            ec.build_event_context(holdings=[], regime="MIXED", now_et=_et(2026, 11, 2, hh), lookup_earnings=False)
        assert sum("CALENDAR GAP" in r.getMessage() for r in caplog.records) == 1
        ec.build_event_context(holdings=[], regime="MIXED", now_et=_et(2026, 11, 3), lookup_earnings=False)
        assert sum("CALENDAR GAP" in r.getMessage() for r in caplog.records) == 2


def test_payload_carries_the_same_warning():
    engine = create_engine("sqlite://")
    try:
        payload = ec.event_risk_payload(engine, "cfg", 10, lambda d: "MIXED", holdings=[],
                                        now_et=_et(2026, 11, 2), horizon_sessions=3)
        assert payload["calendar_gap"]["warning"] == \
            "CALENDAR GAP: no CPI or jobs dates after 2026-12-10 — add them via DAI_EVENT_CALENDAR_FILE"
        assert payload["live"]["calendar_gap"] == payload["calendar_gap"]
        quiet = ec.event_risk_payload(engine, "cfg", 10, lambda d: "MIXED", holdings=[],
                                      now_et=_et(2026, 10, 5), horizon_sessions=3)
        assert quiet["calendar_gap"]["warning"] is None
    finally:
        engine.dispose()


def test_payload_reports_the_gap_even_with_the_block_disabled(monkeypatch):
    monkeypatch.setenv("DAI_EVENT_CALENDAR_ENABLED", "0")
    engine = create_engine("sqlite://")
    try:
        payload = ec.event_risk_payload(engine, "cfg", 10, lambda d: "MIXED", now_et=_et(2026, 11, 2),
                                        horizon_sessions=2)
        assert payload["calendar_gap"]["warning"].startswith("CALENDAR GAP:")
    finally:
        engine.dispose()


def test_dashboard_card_and_feedback_tab_show_the_warning():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    server = (root / "dashboard_server.py").read_text(encoding="utf-8")
    assert '"calendar_gap": (_live.get("calendar_gap") or {}).get("warning")' in server
    card = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "{% if event_risk.calendar_gap %}" in card and "{{ event_risk.calendar_gap }}" in card
    tab = (root / "templates" / "feedback_dashboard.html").read_text(encoding="utf-8")
    assert 'id="eventCalendarGap"' in tab
    js = (root / "static" / "js" / "feedback.js").read_text(encoding="utf-8")
    assert "renderCalendarGap(payload.calendar_gap)" in js and "el.textContent" in js
