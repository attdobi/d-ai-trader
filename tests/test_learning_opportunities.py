"""Prospective denominators, immutable context, and paper-return alignment."""
from datetime import datetime, timezone
import ast
import logging
import json
from pathlib import Path
import threading
from types import MethodType, SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from policy_graph import opportunities as O


OBSERVED = "2026-09-04T18:00:00+00:00"  # Friday, 14:00 ET, before Labor Day
NOW = "2026-09-16T22:00:00+00:00"


@pytest.fixture
def engine():
    e = create_engine("sqlite://")
    O.ensure_schema(e)
    return e


def snapshot(engine, run="r1", ticker="AAPL", **kwargs):
    return O.record_snapshot(engine, "cfg", run, [{"ticker": ticker, "price": 100, "setup": "pullback"}],
                             observed_at=OBSERVED, input_id=10, prompt_version=59, **kwargs)


def cases(engine, config="cfg"):
    return O.list_cases(engine, config, days=3650)


def base_case(ticker="AAPL", ident=1, action="BUY", observed=OBSERVED):
    return {"id": ident, "ticker": ticker, "observed_at": observed, "coverage": "prospective_screener",
            "eligible_for_recall": True, "action": action, "side_cost_bps": 10, "spec_id": O.SPEC_ID}


def bars():
    return [{"date": d, "open": 100, "low": 98, "high": 106+i, "close": 102+i, "adjusted": True}
            for i,d in enumerate(["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"])]


def matured_case(ticker, ident, action, value, **extra):
    c = base_case(ticker, ident, action)
    c.update(extra)
    c["outcomes"] = {"3": {"status": "matured", "net_return_pct": value,
                            "label": "winner" if value>0 else "loser" if value<0 else "break_even"}}
    return c


def test_snapshot_is_config_scoped_immutable_and_idempotent(engine):
    assert snapshot(engine) == 1
    O.record_snapshot(engine, "cfg", "r1", [{"ticker":"AAPL", "price":999}],
                      observed_at="2026-09-09T12:00:00Z", input_id=999, prompt_version=99)
    O.record_snapshot(engine, "other", "r1", [{"ticker":"AAPL"}], observed_at=OBSERVED)
    rows = cases(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["reference_price"] == 100 and row["input_id"] == 10 and row["prompt_version"] == 59
    assert row["observed_at"] == OBSERVED and row["eligible_for_recall"]
    assert row["reference_asof"] is None and row["reference_source"] == "screener_snapshot"
    assert row["spread_bps"] is None and row["tradable"] is None
    assert len(cases(engine,"other")) == 1


def test_known_context_is_distinct_from_screener_denominator(engine):
    snapshot(engine, context={"regime":"RISK-OFF", "news":["MSFT"], "watchlist":["AAPL","NVDA"], "holdings":["CASH"]})
    rows = {r["ticker"]:r for r in cases(engine)}
    assert set(rows) == {"AAPL","MSFT","NVDA"}
    assert rows["AAPL"]["features"]["regime"] == "RISK-OFF"
    assert rows["AAPL"]["coverage"] == "prospective_screener"
    assert not rows["MSFT"]["eligible_for_recall"]
    assert rows["MSFT"]["coverage"] == "prospective_context"


def test_holdings_quarantine_and_explicit_untradable_are_excluded(engine):
    snapshot(engine, holdings=[{"ticker":"AAPL"}])
    snapshot(engine,"r2","MSFT",quarantined={"MSFT"})
    O.record_snapshot(engine,"cfg","r3",[{"ticker":"NVDA","tradable":False}],observed_at=OBSERVED)
    assert all(not r["eligible_for_recall"] for r in cases(engine))


def test_invalid_tickers_nonfinite_features_and_future_quote_do_not_leak(engine):
    O.record_snapshot(engine,"cfg","r",[
        {"ticker":"CASH"}, {"ticker":"AAPL; DROP TABLE x"}, {"ticker":""},
        {"ticker":"MSFT","price":100,"price_asof":"2026-10-01T00:00:00Z","score":float("nan"),"secret":"not stored"},
        {"ticker":"BRK.B","price":float("inf"),"spread_bps":-5},
    ], observed_at=OBSERVED)
    rows={r["ticker"]:r for r in cases(engine)}
    assert set(rows)=={"MSFT","BRK.B"}
    assert rows["MSFT"]["reference_price"] is None
    assert "price" not in rows["MSFT"]["features"] and "score" not in rows["MSFT"]["features"]
    assert "secret" not in rows["MSFT"]["features"]
    assert rows["BRK.B"]["reference_price"] is None and rows["BRK.B"]["spread_bps"] is None


def test_model_actions_do_not_imply_fills_and_response_only_names_are_not_recall(engine):
    snapshot(engine)
    reply={"decisions":[{"ticker":"AAPL","action":"BUY","reason":"reclaim","cited":["DA.rule"]}],
           "considered":[{"ticker":"AAPL","verdict":"pass"},{"ticker":"MSFT","verdict":"reject","why":"event"}]}
    assert O.record_decisions(engine,"cfg","r1",reply,recorded_at=NOW)==2
    assert O.record_decisions(engine,"cfg","r1",{"ticker":"AAPL","action":"SELL"},recorded_at=NOW)==0
    rows={r["ticker"]:r for r in cases(engine)}
    assert rows["AAPL"]["action"]=="BUY" and rows["AAPL"]["cited"]==["DA.rule"]
    assert rows["MSFT"]["action"]=="PASS" and rows["MSFT"]["coverage"]=="postdecision"
    assert not rows["MSFT"]["eligible_for_recall"]
    assert "execution_status" not in rows["AAPL"]


def test_absent_assessment_stays_unknown_instead_of_becoming_pass(engine):
    snapshot(engine)
    O.record_decisions(engine,"cfg","r1",{"cash_reason":"nothing","considered":True},recorded_at=NOW)
    assert cases(engine)[0]["action"]=="NOT_ASSESSED"
    assert O.metrics(cases(engine))["unassessed"]==1


def test_action_write_is_scoped_and_parses_json_without_evaluation(engine):
    snapshot(engine)
    O.record_decisions(engine,"other","r1",'{"ticker":"AAPL","action":"SELL"}',recorded_at=NOW)
    assert cases(engine)[0]["action"]=="NOT_ASSESSED"
    assert cases(engine,"other")[0]["action"]=="SELL"
    assert O.record_decisions(engine,"cfg","r1","not json",recorded_at=NOW)==0


def test_paper_entry_skips_weekend_holiday_and_same_day_price():
    c=base_case()
    c["reference_price"]=999
    result=O.evaluate_case(c,[{"date":"2026-09-04","open":1,"high":2,"low":1,"close":2,"adjusted":True}]+bars(),now=NOW)
    assert result["1"]["entry_date"]=="2026-09-08"
    assert result["1"]["entry_price"]==100 and result["1"]["exit_date"]=="2026-09-08"
    assert result["3"]["exit_date"]=="2026-09-10" and result["5"]["exit_date"]=="2026-09-14"
    assert result["3"]["status"]=="matured" and result["3"]["label"]=="winner"
    assert result["3"]["net_return_pct"] < result["3"]["gross_return_pct"]
    assert result["3"]["mae_pct"]==-2 and result["3"]["mfe_pct"]==8
    assert result["3"]["net_pnl_per_1000"]==pytest.approx(result["3"]["net_return_pct"]*10,abs=1e-6)


def test_daily_close_unavailable_until_after_declared_maturity_even_when_future_bar_supplied():
    result=O.evaluate_case(base_case(),bars(),now="2026-09-10T18:00:00Z")
    assert result["1"]["status"]=="matured"
    assert result["3"]["status"]=="pending" and result["3"]["net_return_pct"] is None


@pytest.mark.parametrize("mutation",["missing", "unadjusted", "negative", "nan", "bad_range"])
def test_incomplete_or_invalid_daily_window_stays_missing_instead_of_shifting(mutation):
    b=bars()
    if mutation=="missing": del b[1]
    elif mutation=="unadjusted": b[1]["adjusted"]=False
    elif mutation=="negative": b[1]["open"]=-1
    elif mutation=="nan": b[1]["close"]=float("nan")
    elif mutation=="bad_range": b[1]["low"]=999
    result=O.evaluate_case(base_case(),b,now=NOW)
    assert result["3"]["status"]=="missing_data" and result["3"]["exit_price"] is None


def test_unknown_calendar_never_guesses_weekday_holidays():
    result=O.evaluate_case(base_case(observed="2027-12-31T12:00:00Z"),bars(),now="2028-01-10T23:00:00Z")
    assert all(x["status"]=="calendar_unknown" for x in result.values())


def test_timezone_uses_new_york_date_for_next_session():
    result=O.evaluate_case(base_case(observed="2026-09-09T01:00:00Z"),bars(),now=NOW)
    assert result["1"]["entry_date"]=="2026-09-09"  # observed Sep8 21:00ET


def test_metrics_define_precision_recall_fpr_on_paired_matured_candidates():
    rows=[matured_case("AAPL",1,"BUY",5),matured_case("MSFT",2,"BUY",-2),
          matured_case("NVDA",3,"PASS",3),matured_case("AMD",4,"PASS",-4),
          matured_case("ORCL",5,"BUY",0)]
    m=O.metrics(rows)
    assert (m["tp"],m["fp"],m["fn"],m["tn"])==(1,1,1,1)
    assert m["precision"]==m["recall"]==m["fpr"]==0.5
    assert m["winner_denominator"]==2 and m["loser_denominator"]==2
    assert m["break_even"]==1 and m["net_expectancy_pct"]==1
    assert m["net_pnl_per_1000"]==30
    assert m["precision_interval"][0]<0.5<m["precision_interval"][1]


def test_metrics_exclude_postdecision_context_unmatured_and_unassessed():
    good=matured_case("AAPL",1,"BUY",5)
    post=matured_case("MSFT",2,"BUY",-2,coverage="postdecision")
    context=matured_case("NVDA",3,"PASS",3,coverage="prospective_context",eligible_for_recall=False)
    pending=base_case("AMD",4,"PASS")
    unknown=base_case("ORCL",5,"NOT_ASSESSED")
    m=O.metrics([good,post,context,pending,unknown])
    assert m["episodes"]==3 and m["matured"]==1 and m["unmatured"]==1 and m["unassessed"]==1
    assert m["recall"]==1 and m["fpr"] is None and m["coverage"]==pytest.approx(2/3)


def test_repeated_ticker_cycles_do_not_replace_first_miss_or_double_count_overlap():
    first=matured_case("AAPL",1,"PASS",4)
    later=matured_case("AAPL",2,"BUY",4,observed_at="2026-09-08T18:00:00Z")
    after=matured_case("AAPL",3,"BUY",4,observed_at="2026-09-11T18:00:00Z")
    m=O.metrics([later,after,first],horizon=3)
    assert m["episodes"]==2 and m["deduplicated"]==1
    assert m["fn"]==1 and m["tp"]==1 and m["recall"]==0.5


def test_empty_metrics_are_unknown_not_zero():
    m=O.metrics([])
    assert m["precision"] is None and m["recall"] is None and m["fpr"] is None
    assert m["net_expectancy_pct"] is None and m["episodes"]==0


def test_matured_status_without_a_finite_return_cannot_enter_quality_denominators():
    c=matured_case("AAPL",1,"BUY",3)
    c["outcomes"]["3"]["net_return_pct"]=float("nan")
    m=O.metrics([c])
    assert m["matured"]==0 and m["precision"] is None


def test_outcome_refresh_is_config_scoped_freezes_matured_and_recovers_missing(engine):
    snapshot(engine)
    O.record_decisions(engine,"cfg","r1",{"ticker":"AAPL","action":"BUY"},recorded_at=NOW)
    O.record_snapshot(engine,"other","r2",[{"ticker":"MSFT"}],observed_at=OBSERVED)
    first=O.refresh_outcomes(engine,"cfg",loader=lambda *_:[],now=NOW)
    assert first["outcomes_written"]==3
    assert cases(engine)[0]["outcomes"]["3"]["status"]=="missing_data"
    O.refresh_outcomes(engine,"cfg",loader=lambda *_:bars(),now="2026-09-17T06:00:00Z")
    row=cases(engine)[0]
    assert row["outcomes"]["3"]["status"]=="matured"
    expected=row["outcomes"]["3"]["net_return_pct"]
    second=O.refresh_outcomes(engine,"cfg",loader=lambda *_:[],now=NOW)
    assert second["outcomes_written"]==0 and second["tickers"]==0
    assert cases(engine)[0]["outcomes"]["3"]["net_return_pct"]==expected
    assert cases(engine,"other")[0]["outcomes"]=={}


def test_failed_source_leaves_pending_without_inventing_return(engine):
    snapshot(engine)
    def fail(*_): raise RuntimeError("unavailable")
    result=O.refresh_outcomes(engine,"cfg",loader=fail,now=NOW)
    assert result["source_failures"]==1 and cases(engine)[0]["outcomes"]=={}


def test_refresh_limits_distinct_tickers_and_chooses_oldest_pending(engine):
    for i,t in enumerate(["AAPL","MSFT","NVDA"]):
        snapshot(engine,"r"+str(i),t)
    result=O.refresh_outcomes(engine,"cfg",loader=lambda *_:bars(),now=NOW,max_tickers=1)
    assert result["tickers"]==1
    assert sum(bool(c["outcomes"]) for c in cases(engine))==1


def test_public_contract_never_accepts_arbitrary_horizon():
    with pytest.raises(ValueError): O.evaluate_case(base_case(),bars(),now=NOW,horizons=[2])
    with pytest.raises(ValueError): O.metrics([],horizon=2)


def test_cost_assumption_must_be_valid():
    c=base_case(); c["side_cost_bps"]=-1
    with pytest.raises(ValueError): O.evaluate_case(c,bars(),now=NOW)


def _orchestrator_functions(**overrides):
    """Execute only scheduling methods, avoiding config/trader imports and startup."""
    source=Path(__file__).resolve().parents[1]/"d_ai_trader.py"
    tree=ast.parse(source.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="DAITraderOrchestrator")
    funcs=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {"scheduled_learning_outcomes_job","setup_schedule"}]
    namespace={"threading":threading,"engine":object(),"get_current_config_hash":lambda:"cfg",
               "logger":logging.getLogger("learning-maintenance-test"), "LOCAL_TZ_ABBR":"test",
               "MarketClock":SimpleNamespace(et_to_local=lambda hhmm:hhmm)}
    namespace.update(overrides)
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(source),"exec"),namespace)
    return namespace


class DeferredThread:
    instances=[]
    def __init__(self,**kwargs):
        self.__dict__.update(kwargs)
        self.started=False
        self.instances.append(self)
    def start(self):
        self.started=True


def test_background_job_returns_before_market_data_and_prevents_overlap(monkeypatch):
    DeferredThread.instances=[]
    queried=[]
    monkeypatch.setattr(O,"has_pending",lambda engine,h:queried.append((engine,h)) or False)
    monkeypatch.setattr(O,"refresh_outcomes",lambda *_a,**_k:pytest.fail("No pending ledger must not fetch prices"))
    ns=_orchestrator_functions(threading=SimpleNamespace(Thread=DeferredThread))
    host=SimpleNamespace(_learning_outcomes_lock=threading.Lock(),_learning_outcomes_thread=None)
    job=ns["scheduled_learning_outcomes_job"]
    assert job(host) is True and queried==[]
    assert job(host) is False and len(DeferredThread.instances)==1
    worker=DeferredThread.instances[0]
    assert worker.daemon is True and worker.started
    worker.target()
    assert queried==[(ns["engine"],"cfg")]
    assert not host._learning_outcomes_lock.locked()


def test_background_maintenance_is_bounded_scoped_and_releases_after_failure(monkeypatch,caplog):
    DeferredThread.instances=[]
    called=[]
    monkeypatch.setattr(O,"has_pending",lambda *_:True)
    def refresh(engine,h,**kwargs):
        called.append((h,kwargs))
        raise RuntimeError("private connection details must never reach the log")
    monkeypatch.setattr(O,"refresh_outcomes",refresh)
    ns=_orchestrator_functions(threading=SimpleNamespace(Thread=DeferredThread))
    host=SimpleNamespace(_learning_outcomes_lock=threading.Lock(),_learning_outcomes_thread=None)
    ns["scheduled_learning_outcomes_job"](host)
    with caplog.at_level(logging.WARNING): DeferredThread.instances[0].target()
    assert called==[("cfg",{"limit":300,"max_tickers":40})]
    assert not host._learning_outcomes_lock.locked()
    assert "RuntimeError" in caplog.text and "private connection details" not in caplog.text


def test_scheduler_registers_daily_1715_eastern_worker_without_invoking_it():
    import schedule
    scheduler=schedule.Scheduler()
    ns=_orchestrator_functions(schedule=SimpleNamespace(every=scheduler.every))
    host=SimpleNamespace(_cadence_minutes=180,market_open_job=lambda:None,cadence_tick=lambda:None,
                         scheduled_feedback_job=lambda:None,_run_market_open_catchup_if_needed=lambda:None,
                         _learning_outcomes_lock=threading.Lock(),_learning_outcomes_thread=None)
    host.scheduled_learning_outcomes_job=MethodType(ns["scheduled_learning_outcomes_job"],host)
    ns["setup_schedule"](host)
    learning=[j for j in scheduler.jobs if j.job_func.func==host.scheduled_learning_outcomes_job]
    assert len(learning)==1 and str(learning[0].at_time)=="17:15:00"
    assert learning[0].at_time_zone.zone=="America/New_York"
    assert host._learning_outcomes_thread is None


def test_has_pending_is_scoped_and_becomes_false_when_all_horizons_mature(engine):
    assert not O.has_pending(engine,"cfg",days=3650)
    snapshot(engine)
    assert O.has_pending(engine,"cfg",days=3650) and not O.has_pending(engine,"other",days=3650)
    O.refresh_outcomes(engine,"cfg",loader=lambda *_:bars(),now=NOW)
    assert not O.has_pending(engine,"cfg",days=3650)


def test_report_metrics_use_entire_prospective_cohort_despite_over_500_display_rows(engine):
    snapshot(engine,"first")
    O.record_decisions(engine,"cfg","first",{"ticker":"AAPL","action":"PASS"},recorded_at=NOW)
    O.record_snapshot(engine,"cfg","context",[],observed_at="2026-09-05T18:00:00Z",
                      context={"news":[f"T{i:04d}" for i in range(600)]})
    O.record_snapshot(engine,"cfg","later",[{"ticker":"AAPL"}],observed_at="2026-09-08T18:00:00Z")
    O.record_decisions(engine,"cfg","later",{"ticker":"AAPL","action":"BUY"},recorded_at=NOW)
    b=bars()+[{"date":"2026-09-15","open":100,"low":98,"high":110,"close":107,"adjusted":True}]
    for case in [c for c in O.list_cases(engine,"cfg",days=3650,limit=5000) if c["coverage"]=="prospective_screener"]:
        with engine.begin() as conn:
            for horizon,outcome in O.evaluate_case(case,b,now=NOW).items():
                conn.execute(text("INSERT INTO learning_opportunity_outcomes (opportunity_id,horizon,status,outcome_json,measured_at) VALUES (:i,:h,:s,:j,:t)"),
                             {"i":case["id"],"h":int(horizon),"s":outcome["status"],"j":json.dumps(outcome),"t":NOW})
    result=O.report(engine,"cfg",days=3650)
    assert result["total_rows"]==602 and result["displayed_rows"]==500
    assert result["cohort_rows"]==2 and not result["cohort_truncated"]
    assert not any(c["run_id"]=="first" for c in result["cases"])
    assert result["metrics"]["fn"]==1 and result["metrics"]["tp"]==0
    assert result["metrics"]["recall"]==0
    assert result["metrics_by_horizon"]["1"]["recall"]==0.5
    assert result["metrics_by_horizon"]["5"]["recall"]==0
    assert "all 2" in result["coverage_note"] and "display limits" in result["coverage_note"]


def test_report_scope_does_not_mix_other_configuration_or_noneligible_rows(engine):
    snapshot(engine)
    O.record_snapshot(engine,"other","r1",[{"ticker":"MSFT"}],observed_at=OBSERVED)
    snapshot(engine,"held","NVDA",holdings=["NVDA"])
    result=O.report(engine,"cfg",days=3650,case_limit=1)
    assert result["total_rows"]==2 and result["displayed_rows"]==1 and result["cohort_rows"]==1
    assert set(result["metrics_by_horizon"])=={"1","3","5"}
    assert all(m["episodes"]==1 and m["unassessed"]==1 for m in result["metrics_by_horizon"].values())
    assert result["metrics"]["coverage"]==0 and result["metrics"]["recall"] is None


def test_report_suppresses_all_quality_rates_when_declared_cohort_exceeds_bound(engine,monkeypatch):
    snapshot(engine,"r1","AAPL")
    snapshot(engine,"r2","MSFT")
    monkeypatch.setattr(O,"MAX_REPORT_COHORT",1)
    result=O.report(engine,"cfg",days=3650)
    assert result["cohort_truncated"] and result["cohort_rows"]==2
    for m in result["metrics_by_horizon"].values():
        assert m["precision"] is None and m["recall"] is None and m["fpr"] is None
        assert m["net_expectancy_pct"] is None and m["matured"] is None
    assert "unavailable" in result["coverage_note"]


def test_missing_old_cohort_cannot_starve_new_healthy_ticker_after_bounds(engine):
    for i,ticker in enumerate(["AAPL","MSFT","NVDA"]):
        snapshot(engine,"old"+str(i),ticker)
    O.record_snapshot(engine,"cfg","healthy",[{"ticker":"TSLA"}],observed_at="2026-09-08T18:00:00Z")
    O.record_snapshot(engine,"other","private",[{"ticker":"AMD"}],observed_at=OBSERVED)
    calls=[]
    healthy_bars=bars()+[{"date":"2026-09-15","open":100,"low":98,"high":110,"close":107,"adjusted":True}]
    def loader(ticker,*_):
        calls.append(ticker)
        return healthy_bars if ticker=="TSLA" else []
    O.refresh_outcomes(engine,"cfg",loader=loader,now=NOW,limit=2,max_tickers=2)
    assert calls==["AAPL","MSFT"]
    calls.clear()
    O.refresh_outcomes(engine,"cfg",loader=loader,now=NOW,limit=2,max_tickers=2)
    assert calls==["NVDA","TSLA"]
    rows={c["ticker"]:c for c in cases(engine)}
    assert rows["TSLA"]["outcomes"]["3"]["status"]=="matured"
    assert rows["AAPL"]["outcomes"]["3"]["status"]=="missing_data"
    assert cases(engine,"other")[0]["outcomes"]=={}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM learning_opportunity_attempts WHERE config_hash='other'")).scalar_one()==0


def test_attempt_is_recorded_on_source_failure_and_backoff_prevents_immediate_refetch(engine):
    snapshot(engine)
    calls=[]
    def loader(ticker,*_):
        calls.append(ticker)
        raise RuntimeError("source unavailable")
    O.refresh_outcomes(engine,"cfg",loader=loader,now=NOW)
    with engine.connect() as conn:
        attempt=conn.execute(text("SELECT * FROM learning_opportunity_attempts")).mappings().one()
    assert attempt["status"]=="source_error" and attempt["failures"]==1
    assert attempt["last_attempt_at"]==NOW
    assert attempt["retry_after_at"]>NOW
    O.refresh_outcomes(engine,"cfg",loader=loader,now=NOW)
    assert calls==["AAPL"] and cases(engine)[0]["outcomes"]=={}


def test_missing_old_case_does_not_starve_later_healthy_case_of_same_ticker(engine):
    snapshot(engine,"old")
    O.record_snapshot(engine,"cfg","new",[{"ticker":"AAPL"}],observed_at="2026-09-08T18:00:00Z")
    after_missing=[b for b in bars() if b["date"]!="2026-09-08"]
    O.refresh_outcomes(engine,"cfg",loader=lambda *_:after_missing,now=NOW,limit=1,max_tickers=1)
    O.refresh_outcomes(engine,"cfg",loader=lambda *_:after_missing,now=NOW,limit=1,max_tickers=1)
    rows={c["run_id"]:c for c in cases(engine)}
    assert rows["old"]["outcomes"]["1"]["status"]=="missing_data"
    assert rows["new"]["outcomes"]["1"]["status"]=="matured"
