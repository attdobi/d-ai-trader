from datetime import datetime, timezone
import json

from sqlalchemy import create_engine, event, text

from feedback_learning import learning_report
from policy_graph import opportunities as opp

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)


def test_readonly_report_attribution_intervals_and_pending():
    db = create_engine("sqlite://")
    def candidate(c, ident, date, version, ticker, action, cfg="cfg"):
        c.execute(text("""INSERT INTO learning_opportunities
            (id,config_hash,run_id,input_id,prompt_version,ticker,observed_at,session_date,coverage,
            eligible_for_recall,features_json,action,spec_id,side_cost_bps)
            VALUES (:i,:h,:r,:i,:v,:t,:o,:d,'prospective_screener',TRUE,'{}',:a,:s,10)"""),
            dict(i=ident,h=cfg,r=str(ident),v=version,t=ticker,o=date+"T16:00:00+00:00",d=date,a=action,s=opp.SPEC_ID))
    def summary(c, ident, ticker, verdict, stamp, version=None):
        doc = dict(timestamp=stamp,summary={"headlines":["headline"],"insights":"evidence",
                   "catalyst_validity":[{"ticker":ticker,"tradability":verdict}]})
        if version is not None:
            doc["prompt_provenance"] = {"version":version, "source":"config"}
        timestamp = datetime.strptime(stamp,"%Y%m%dT%H%M%S")
        c.execute(text("INSERT INTO summaries VALUES (:i,'cfg','source',:ts,'batch',:d)"),
                  dict(i=ident,ts=timestamp,d=json.dumps(doc)))
    def input_(c, ident, source_ids):
        images = [{"source_agent":"source","source_run_id":"batch","summary_id":str(sid)} for sid in source_ids]
        c.execute(text("INSERT INTO decider_inputs VALUES (:i,'cfg','decide',:m)"),
                  dict(i=ident,m=json.dumps({"image_manifest":{"images":images}})))
    def outcome(c, ident, label, net, status="matured"):
        c.execute(text("INSERT INTO learning_opportunity_outcomes VALUES (:i,3,:s,:o,'2026-11-17T22:00:00+00:00')"),
                  dict(i=ident,s=status,o=json.dumps({"label":label,"status":status,"net_return_pct":net})))
    with db.begin() as c:
        c.execute(text(opp.DDL_SQLITE))
        c.execute(text(opp.DDL_OUTCOMES_SQLITE))
        c.execute(text("CREATE TABLE decider_inputs(id INTEGER,config_hash TEXT,call_kind TEXT,context_json TEXT)"))
        c.execute(text("CREATE TABLE summaries(id INTEGER,config_hash TEXT,agent TEXT,timestamp TIMESTAMP,run_id TEXT,data TEXT)"))
        candidate(c,1,"2026-11-09",61,"AAA","BUY")
        candidate(c,2,"2026-11-10",62,"AAA","PASS")  # overlaps v61's decision
        candidate(c,3,"2026-11-10",62,"BBB","PASS")
        candidate(c,4,"2026-11-10",62,"CCC","BUY")
        candidate(c,5,"2026-11-10",62,"DDD","NOT_ASSESSED")
        candidate(c,6,"2026-11-10",62,"EEE","PASS")
        candidate(c,7,"2026-11-19",62,"FFF","PASS")
        candidate(c,8,"2026-11-10",62,"GGG","BUY")
        candidate(c,9,"2026-11-11",63,"ZZZ","PASS","different")
        outcome(c,1,"winner",2)
        outcome(c,3,"winner",1)
        outcome(c,4,"loser",-3)
        outcome(c,8,None,None,"missing_data")
        summary(c,1,"AAA","actionable_now","20261109T073000",31)
        summary(c,2,"BBB","watch_only","20261110T073000")
        summary(c,3,"CCC","actionable_now","20261110T073000",32)
        summary(c,4,"CCC","avoid_chasing","20261110T073001",32)
        summary(c,5,"BBB","actionable_now","20261110T091000",32)  # created after snapshot
        input_(c,1,[1,1])  # two screenshots, one prediction
        input_(c,3,[2,5])
        input_(c,4,[3,4])
    # The report must work on a read-only connection.
    @event.listens_for(db, "before_cursor_execute")
    def check(_conn,_cursor,statement,_params,_context,_many):
        assert statement.lstrip().upper().startswith("SELECT")
    d = learning_report(db, "cfg", horizon=3,now=NOW)
    assert d["candidate_rows"] == 8 and d["episodes"] == 7
    versions = {r["label"]:r for r in d["decider"]["version"]}
    assert set(versions) == {"v61","v62"}
    assert versions["v61"]["recall_interval"][0] < .3
    assert versions["v61"]["net_expectancy_pct"] == 2
    v = versions["v62"]
    assert (v["tp"],v["fp"],v["fn"],v["tn"],v["fpr"],v["recall"]) == (0,1,1,0,1,0)
    assert (v["buys"],v["passes"],v["unassessed"],v["matured"],v["pending"],v["overdue"],v["missing"]) == (2,3,1,2,1,1,1)
    assert v["net_expectancy_pct"] == -3 and v["matured_buys"] == 1
    assert [r["label"] for r in d["decider"]["week"]] == ["2026-11-16","2026-11-09"]
    sr = d["summarizer"]
    assert sr["signals"] == 2 and sr["summaries"] == 5 and sr["unattributed"] == 1
    summaries = {r["label"]:r for r in sr["version"]}
    assert summaries["v31"]["tp"] == 1 and summaries["Unattributed"]["fn"] == 1
    assert summaries["v32"]["episodes"] == 0 and summaries["v32"]["recall"] is None
    db.dispose()


def test_evidence_packet_is_bounded_allowlisted_and_matches_dashboard(monkeypatch):
    from feedback_learning import review_evidence, review_evidence_text
    template = dict(first='2026-11-11', last='2026-11-19', episodes=24, assessed=10, matured=3,
                    pending=4, overdue=2, missing=1, buys=2, passes=8, matured_buys=1, tp=1, fp=0,
                    fn=2, tn=0, recall_interval=[.06,.79], fpr_interval=None, net_expectancy_pct=1.1655,
                    untrusted_source_text="NEVER INCLUDE THIS")
    versions = [dict(template, label=f"v{version}") for version in range(9,2,-1)]
    report = dict(status='ok',start='start',as_of='end',candidate_rows=38,episodes=24,
                  decider={'version':versions}, summarizer={'status':'ok','version':[],
                  'summaries':10,'unattributed':10,'signals':0})
    monkeypatch.setattr("feedback_learning.learning_report",lambda *args,**kwargs:report)
    packet=review_evidence(None,"cfg")
    assert len(packet["decider"]["latest_groups"]) == 3 and packet["decider"]["recorded_groups"] == 7
    cohort=packet["decider"]["latest_groups"][0]
    assert cohort["gain_recall"] == {"hits":1,"denominator":3,"wilson95_pct":[6.,79.]}
    assert cohort["loss_fpr"] == {"hits":0,"denominator":0,"wilson95_pct":None}
    assert packet["summarizer"]["unversioned_summaries"] == 10
    assert "NEVER INCLUDE" not in review_evidence_text(packet)
    def broken(*args, **kwargs):
        raise RuntimeError("sensitive detail")
    monkeypatch.setattr("feedback_learning.learning_report",broken)
    missing=review_evidence(None,"cfg")
    assert missing["status"]=="unavailable" and "sensitive" not in review_evidence_text(missing)


def test_execution_coverage_scopes_verified_closures_and_unscored_submissions_separately():
    from datetime import timedelta
    from feedback_metrics import execution_coverage
    from strategy_exit_accounting import DDL
    db = create_engine("sqlite://")
    end = opp._now("2026-11-23T19:00:00Z")
    start = end - timedelta(days=30)
    t = end.replace(tzinfo=None) - timedelta(hours=1)
    with db.begin() as c:
        assert execution_coverage(c,"cfg",start,end) == {"closures": None, "exit_orders": None}
        c.execute(text("""CREATE TABLE trade_outcomes(id INTEGER,config_hash TEXT,ticker TEXT,sell_timestamp TIMESTAMP,
            original_reason TEXT,market_context TEXT)"""))
        for cfg, ticker, date, source in (
            ("cfg","AAA",t,"schwab_transactions"),("cfg","BBB",t,None),("other","AAA",t,"schwab_transactions"),
            ("cfg","CCC",t-timedelta(days=32),None),("cfg","N/A",t,None)):
            c.execute(text("INSERT INTO trade_outcomes VALUES(1,:cfg,:ticker,:t,'',:ctx)"),
                dict(cfg=cfg,ticker=ticker,t=date,ctx=json.dumps({"strategy_execution":{"source":source}})))
        assert execution_coverage(c,"cfg",start,end) == {"closures":{"matched_fills":1,"legacy_recorded":1},
                                                         "exit_orders":None}
        c.execute(text(DDL))
        for no, (cfg,state,date,checked) in enumerate((
            ("cfg","scored",t,t), ("cfg","unscored",t,t), ("cfg","unfilled",t,t),
            ("cfg","pending",t,None), ("cfg","scored",t,t+timedelta(days=2)),
            ("other","pending",t,None), ("cfg","pending",t-timedelta(days=40),None))):
            c.execute(text("""INSERT INTO strategy_exit_accounting
                (config_hash,exit_order_id,ticker,held_before,observed_at,status,last_checked_at)
                VALUES(:cfg,:i,'AAA',1,:date,:state,:checked)"""),dict(cfg=cfg,i=str(no),date=date,state=state,checked=checked))
        assert execution_coverage(c,"cfg",start,end)["exit_orders"] == {
            "scored":1,"pending":2,"unscored":1,"unfilled":1}
