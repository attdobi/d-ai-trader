"""Exercise the startup scheduler without importing the live trader."""

import ast
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import schedule


EASTERN = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")
SOURCE = Path(__file__).resolve().parents[1] / "d_ai_trader.py"


def make_scheduler():
    methods = {"run", "setup_schedule", "_run_market_open_catchup_if_needed",
               "_ensure_cadence_anchor", "_configure_resume_cadence", "cadence_tick"}
    module = ast.parse(SOURCE.read_text())
    trader = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "DAITraderOrchestrator")
    trader.body = [node for node in trader.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    scheduler = schedule.Scheduler()
    clock = SimpleNamespace(current=datetime(2026, 11, 11, 8, 40, tzinfo=PACIFIC))

    def stop_loop():
        raise KeyboardInterrupt

    ns = {
        "datetime": SimpleNamespace(now=lambda zone: clock.current.astimezone(zone), fromisoformat=datetime.fromisoformat),
        "timedelta": timedelta,
        "EASTERN_TIMEZONE": EASTERN,
        "LOCAL_TZ_ABBR": "PST",
        "MarketClock": SimpleNamespace(et_to_local=lambda hhmm: {"09:30": "06:30", "20:30": "17:30"}[hhmm]),
        "os": os,
        "schedule": SimpleNamespace(every=scheduler.every, run_pending=stop_loop),
        "logger": logging.getLogger(__name__),
    }
    exec(compile(ast.Module(body=[trader], type_ignores=[]), str(SOURCE), "exec"), ns)
    host = ns[trader.name]()
    host._cadence_minutes = 120
    host._startup_time_et = clock.current.astimezone(EASTERN)
    host._startup_cadence_anchor_et = host._startup_time_et + timedelta(minutes=120)
    host._next_cadence_run_et = None
    host._startup_cycle_completed = False
    host._market_open_run_date = None
    host.sync_policy_graph_latest = lambda _reason: None
    host.scheduled_feedback_job = lambda: None
    host.scheduled_learning_outcomes_job = lambda: None
    called = []

    def market_open():
        called.append("open")
        host._startup_cycle_completed = True

    host.market_open_job = market_open
    host.run_summarizer_agents = lambda: called.append("startup summarizer")
    host.run_decider_agent = lambda **_: called.append("startup decider")
    host.scheduled_summarizer_and_decider_job = lambda: called.append("cadence")
    return host, clock, called, scheduler


def test_resume_skips_startup_and_keeps_next_slot(monkeypatch):
    monkeypatch.setenv("DAI_SKIP_STARTUP_CYCLE", "1")
    monkeypatch.setenv("DAI_RESUME_CADENCE_AT", "2026-11-11T09:38:35-08:00")
    host, clock, called, scheduler = make_scheduler()
    host.run()
    assert called == []
    assert any(job.job_func.func is host.market_open_job for job in scheduler.jobs)

    target = datetime.fromisoformat("2026-11-11T09:38:35-08:00")
    clock.current = target - timedelta(seconds=1)
    host.cadence_tick()
    assert called == []
    clock.current = target
    host.cadence_tick()
    assert called == ["cadence"]
    assert host._next_cadence_run_et == target + timedelta(minutes=120)


def test_normal_start_keeps_market_open_catchup(monkeypatch):
    monkeypatch.delenv("DAI_SKIP_STARTUP_CYCLE", raising=False)
    monkeypatch.setenv("DAI_RESUME_CADENCE_AT", "2026-11-11T09:38:35-08:00")
    host, _, called, _ = make_scheduler()
    host.run()
    assert called == ["open"]
    assert host._startup_cadence_anchor_et == host._startup_time_et + timedelta(minutes=120)


@pytest.mark.parametrize("invalid_slot", ["2026-11-11T08:00:00-08:00", "2026-11-11T09:38:35"])
def test_invalid_resume_slot_keeps_no_startup_safety(monkeypatch, invalid_slot):
    monkeypatch.setenv("DAI_SKIP_STARTUP_CYCLE", "1")
    monkeypatch.setenv("DAI_RESUME_CADENCE_AT", invalid_slot)
    host, _, called, _ = make_scheduler()
    host.run()
    host.cadence_tick()
    assert called == []
    assert host._next_cadence_run_et == host._startup_time_et + timedelta(minutes=120)
