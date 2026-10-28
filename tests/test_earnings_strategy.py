"""Event dollars, provenance and final-order behavior; no live clients or credentials."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, text

import earnings_strategy as es

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_tickets(monkeypatch):
    es._TICKETS.clear()
    monkeypatch.delenv("DAI_EVENT_CALENDAR_FILE", raising=False)
    yield
    es._TICKETS.clear()


def context(day="2026-10-29", **event_updates):
    row = dict(ticker="MSFT", date=day, sessions_to=1, source="yfinance", estimate=False,
               fetched_at=NOW.isoformat(), release_timing="unknown")
    row.update(event_updates)
    return dict(as_of=NOW.isoformat(), earnings_controls_version=1,
                holdings_earnings=[], watchlist_earnings=[row])


def decision(**changes):
    row = dict(action="buy", ticker="MSFT", amount_usd=900, reason="R1 confirmed setup;K:99;D:1%",
               strategy="earnings_event", earnings_event=dict(date="2026-10-29", hold_through=True,
                                                              gap_risk_accepted=True))
    row.update(changes)
    return row


def book(ctx=None, **changes):
    args = dict(config_hash="cfg", context=ctx or context(), account_value=10000,
                normal_position_cap=2000, observed=NOW)
    args.update(changes)
    return es.EventBook(**args)


@pytest.mark.parametrize("equity,normal,expected", [(10000,2000,500), (4000,2000,200),
                         (20000,1000,250), (None,2000,0), (10000,0,0), (float('nan'),2000,0)])
def test_cap_uses_the_smallest_absolute_equity_and_ordinary_limit(equity, normal, expected):
    assert es.event_cap(equity, normal) == expected


def test_authorization_caps_model_allocation_and_requires_explicit_gap_intent():
    d = decision()
    assert not book().authorize(d, minimum=400)
    assert d["amount_usd"] == 500 and d["amount_usd_requested"] == 900
    assert d["earnings_event_controls"]["gap_loss_bound"] == "full position notional"
    assert es.MARKER in d["reason"]
    es.release(d)
    for intent in ({}, {"date":"2026-10-29", "hold_through":True},
                   {"date":"2026-10-30", "hold_through":True, "gap_risk_accepted":True}):
        assert book().authorize(decision(earnings_event=intent), minimum=400)


@pytest.mark.parametrize("row_change,ctx_change", [
    ({"estimate":True}, {}), ({"source":"LLM"}, {}), ({"fetched_at":None}, {}),
    ({"fetched_at":(NOW-timedelta(hours=13)).isoformat()}, {}),
    ({"fetched_at":(NOW+timedelta(seconds=1)).isoformat()}, {}),
    ({}, {"as_of":None}), ({}, {"as_of":(NOW-timedelta(minutes=31)).isoformat()}),
    ({}, {"earnings_controls_version":0}), ({"date":"2026-11-10"}, {}),
    ({"date":"2026-10-27"}, {})])
def test_unknown_stale_estimated_and_out_of_window_events_fail_closed(row_change, ctx_change):
    ctx=context(**row_change); ctx.update(ctx_change)
    assert book(ctx).authorize(decision(), minimum=400)


def test_today_needs_future_release_timing_and_never_accepts_already_released():
    ctx=context(day="2026-10-28", sessions_to=0)
    d=decision(earnings_event=dict(date="2026-10-28", hold_through=True, gap_risk_accepted=True))
    assert book(ctx).authorize(d, minimum=400)
    ctx["watchlist_earnings"][0]["release_timing"]="after_close"
    assert not book(ctx).authorize(d, minimum=400)
    es.release(d)
    ctx["watchlist_earnings"][0]["release_at"]=(NOW-timedelta(hours=1)).isoformat()
    assert "already occurred" in book(ctx).authorize(d, minimum=400)


@pytest.mark.parametrize("holdings,pending", [
    ([dict(ticker="MSFT", current_value=100)], []),
    ([dict(ticker="GOOG", current_value=100, reason="[earnings_event] prior entry")], []),
    ([dict(ticker="MSFT", current_value=None)], []),
    ([], [dict(ticker="MSFT", amount_usd=100)])])
def test_any_existing_event_exposure_or_pending_order_blocks_another(holdings, pending):
    assert "exposure" in book(holdings=holdings,pending=pending).authorize(decision(), minimum=400)


def test_insufficient_cap_does_not_override_normal_minimum_or_force_a_trade():
    assert "minimum" in book(account_value=4000).authorize(decision(), minimum=400)


def test_two_separate_validator_books_cannot_reserve_two_event_trades():
    assert not book().authorize(decision(), minimum=400)
    assert "reserved" in book().authorize(decision(), minimum=400)


def test_final_order_is_whole_share_limit_never_rounds_up_or_reuses_submission():
    d=decision()
    assert not book().authorize(d,minimum=400)
    args=dict(config_hash="cfg",market_open=True,account_value=10000,normal_position_cap=2000,
              holdings=[],pending=[],now=NOW)
    assert es.execution_limit(d,210.129,**args)==(2,210.12,500)
    with pytest.raises(ValueError,match="one whole share"):
        es.execution_limit(d,501,**args)
    with pytest.raises(ValueError,match="regular market"):
        es.execution_limit(d,190,**dict(args,market_open=False))
    with pytest.raises(ValueError,match="authorization"):
        es.execution_limit(d,190,**dict(args,config_hash="other"))
    with pytest.raises(ValueError,match="held or pending"):
        es.execution_limit(d,190,**dict(args,pending=[dict(ticker="GOOG",amount_usd=100)]))
    es.mark_submitted(d,now=NOW)
    with pytest.raises(ValueError,match="already submitted"):
        es.execution_limit(d,190,**args)


def test_final_execution_rechecks_changed_equity_and_current_holdings():
    d=decision(); assert not book().authorize(d,minimum=400)
    args=dict(config_hash="cfg",market_open=True,account_value=9000,normal_position_cap=2000,
              holdings=[],pending=[],now=NOW)
    assert es.execution_limit(d,150,**args)==(3,150,450)
    with pytest.raises(ValueError,match="minimum buy"):
        es.execution_limit(d,150,**dict(args,account_value=4000))
    with pytest.raises(ValueError,match="held or pending"):
        es.execution_limit(d,150,**dict(args,holdings=[dict(ticker="MSFT",current_value=150)]))


def test_model_cannot_forge_server_authorization():
    d=decision(_earnings_authorization="invented",earnings_event_controls=dict(cap_usd=500))
    with pytest.raises(ValueError,match="authorization"):
        es.execution_limit(d,100,config_hash="cfg",market_open=True,holdings=[],pending=[],now=NOW)


def test_validator_preserves_cash_and_ordinary_minimum_and_requires_explicit_strategy(monkeypatch):
    import decision_validator as dv
    monkeypatch.setattr(dv,"MIN_BUY_AMOUNT",400)
    monkeypatch.setattr(dv,"MAX_BUY_AMOUNT",2500)
    v=dv.DecisionValidator([],450,earnings_book=book())
    valid,invalid=v.validate_decisions([decision()])
    assert not valid and "cash" in invalid[0]["validation_error"]
    v=dv.DecisionValidator([],10000,earnings_book=book())
    valid,invalid=v.validate_decisions([decision(strategy="standard")])
    assert not valid and "explicit capped" in invalid[0]["validation_error"]
    valid,invalid=v.validate_decisions([decision()])
    assert len(valid)==1 and not invalid and valid[0]["amount_usd"]==500
    assert v.available_cash==9500


def test_saved_runtime_contract_and_calendar_must_match_exact_run_and_config():
    engine=create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE event_risk_snapshots(id INTEGER,config_hash TEXT,run_id TEXT,as_of TEXT,session_date TEXT,holdings_earnings TEXT,watchlist_earnings TEXT,allowance TEXT)"))
        c.execute(text("CREATE TABLE decider_inputs(id INTEGER,config_hash TEXT,run_id TEXT,call_kind TEXT,user_prompt TEXT)"))
        c.execute(text("INSERT INTO event_risk_snapshots VALUES(1,'cfg','run',:t,'2026-10-28','[]',:e,'{}')"),
                  dict(t=NOW.isoformat(),e=json.dumps(context()["watchlist_earnings"])))
        c.execute(text("INSERT INTO decider_inputs VALUES(1,'cfg','run','decide','old prompt')"))
    assert es.load_run_context(engine,"cfg","run") is None
    with engine.begin() as c:
        c.execute(text("UPDATE decider_inputs SET user_prompt=:p"),dict(p="OPPORTUNITY CHARTER requires "+es.CONTRACT))
    assert es.load_run_context(engine,"cfg","run") is None
    with engine.begin() as c:
        c.execute(text("UPDATE decider_inputs SET user_prompt=:p"),dict(p=es.format_controls(context(),[],10000,2000,config_hash="cfg")))
    assert es.load_run_context(engine,"cfg","run") is None
    with engine.begin() as c:
        c.execute(text("UPDATE event_risk_snapshots SET allowance=:a"),dict(a=json.dumps({"earnings_controls_version":1})))
    assert es.load_run_context(engine,"cfg","run")["watchlist_earnings"][0]["ticker"]=="MSFT"
    assert es.load_run_context(engine,"other","run") is None
    assert es.load_run_context(engine,"cfg","other") is None


def test_pending_day_order_survives_working_and_filled_status_until_explicit_cancellation():
    engine=create_engine("sqlite://")
    d=decision(order_id="1",execution_status="working")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER,config_hash TEXT,timestamp TEXT,data TEXT)"))
        c.execute(text("INSERT INTO trade_decisions VALUES(1,'cfg',:t,:d)"),dict(t=NOW.isoformat(),d=json.dumps([d])))
    assert len(es.pending_orders(engine,"cfg",now=NOW))==1
    assert not es.pending_orders(engine,"other",now=NOW)
    d["execution_status"]="filled"
    with engine.begin() as c:
        c.execute(text("UPDATE trade_decisions SET data=:d"),dict(d=json.dumps([d])))
    assert len(es.pending_orders(engine,"cfg",now=NOW))==1
    d["execution_status"]="canceled"
    with engine.begin() as c:
        c.execute(text("UPDATE trade_decisions SET data=:d"),dict(d=json.dumps([d])))
    assert not es.pending_orders(engine,"cfg",now=NOW)


def test_missing_order_log_is_not_treated_as_zero_open_orders():
    assert es.pending_orders(create_engine("sqlite://"),"cfg",now=NOW)[0]["ticker"]=="UNKNOWN_ORDER_STATE"


def test_durable_submission_reserves_before_order_id_and_survives_restart():
    engine=create_engine("sqlite://")
    d=decision(_earnings_run_id="run"); assert not book().authorize(d,minimum=400)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER,config_hash TEXT,run_id TEXT,timestamp TEXT,data TEXT)"))
        c.execute(text("INSERT INTO trade_decisions VALUES(1,'cfg','run',:t,:d)"),dict(t=NOW.isoformat(),d=json.dumps([d])))
    es.reserve_submission(engine,d,"cfg",now=NOW)
    assert d["execution_status"]=="submitting" and not d.get("order_id")
    es._TICKETS.clear()  # process restart loses every in-memory ticket
    pending=es.pending_orders(engine,"cfg",now=NOW)
    assert len(pending)==1 and pending[0]["earnings_submission"]["reservation_id"]
    with pytest.raises(ValueError,match="already reserved"):
        es.reserve_submission(engine,d,"cfg",now=NOW)
    assert "exposure" in book(pending=pending).authorize(decision(),minimum=400)
    assert not es.pending_orders(engine,"cfg",now=NOW.replace(hour=21))
    with engine.begin() as c:
        d["execution_status"]="rejected"
        c.execute(text("UPDATE trade_decisions SET data=:d"),dict(d=json.dumps([d])))
    assert not es.pending_orders(engine,"cfg",now=NOW)


def test_durable_reservation_requires_saved_server_ticket_and_exact_account():
    engine=create_engine("sqlite://")
    d=decision(_earnings_run_id="run"); assert not book().authorize(d,minimum=400)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER,config_hash TEXT,run_id TEXT,timestamp TEXT,data TEXT)"))
        c.execute(text("INSERT INTO trade_decisions VALUES(1,'cfg','run',:t,:d)"),dict(t=NOW.isoformat(),d=json.dumps([dict(d,_earnings_authorization="fake")])))
    with pytest.raises(ValueError,match="does not match"):
        es.reserve_submission(engine,d,"cfg",now=NOW)
    with pytest.raises(ValueError,match="not saved"):
        es.reserve_submission(engine,d,"other",now=NOW)


def test_two_processes_cannot_claim_the_same_durable_day_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    engine=create_engine("sqlite:///"+str(tmp_path/"reservations.sqlite"))
    first=decision(_earnings_run_id="run1"); assert not book().authorize(first,minimum=400)
    es._TICKETS.clear()  # a second process has independent memory
    second=decision(_earnings_run_id="run2"); assert not book().authorize(second,minimum=400)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER,config_hash TEXT,run_id TEXT,timestamp TEXT,data TEXT)"))
        for i,d in enumerate((first,second),1):
            c.execute(text("INSERT INTO trade_decisions VALUES(:i,'cfg',:r,:t,:d)"),
                      dict(i=i,r=d["_earnings_run_id"],t=NOW.isoformat(),d=json.dumps([d])))
    barrier=threading.Barrier(2)
    def submit(d):
        barrier.wait(timeout=2)
        try:
            es.reserve_submission(engine,d,"cfg",now=NOW)
            return "reserved"
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,(first,second)))
    assert results.count("reserved")==1
    assert sum("already reserved" in r for r in results)==1
    assert len(es.pending_orders(engine,"cfg",now=NOW))==1


def test_confirmed_post_release_opportunity_can_use_standard_strategy(monkeypatch):
    import decision_validator as dv
    monkeypatch.setattr(dv,"MIN_BUY_AMOUNT",400)
    monkeypatch.setattr(dv,"MAX_BUY_AMOUNT",2500)
    ctx=context(day="2026-10-28",sessions_to=0,release_at=(NOW-timedelta(hours=1)).isoformat())
    # This test freezes the check at the calendar's observation time.
    original=es.now_utc
    monkeypatch.setattr(es,"now_utc",lambda value=None:original(value or NOW))
    v=dv.DecisionValidator([],10000,earnings_book=book(ctx))
    valid,invalid=v.validate_decisions([decision(strategy="standard")])
    assert len(valid)==1 and not invalid
