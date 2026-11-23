import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text

from policy_graph import opportunities as opp, selloffs

FRIDAY = opp._now("2026-11-20T20:45:00Z")
MONDAY = opp._now("2026-11-23T14:31:00Z")
SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def context():
    return {"trend": SYMBOLS, "holdings": ["EEE"], "quarantined": ["CCC"]}


def momentum():
    return [dict(symbol=t, price=40, volume=250000, daily_pct=-8, price_asof=FRIDAY.isoformat(),
                 volume_session="2026-11-20") for t in SYMBOLS]


def snapshot(engine, run, input_id, at=FRIDAY):
    candidates = selloffs.select_candidates(momentum(), context(), at)
    opp.record_snapshot(engine, "cfg", run, [], context=context(), observed_at=at,
                        input_id=input_id, selloff_candidates=candidates)


def test_selection_requires_supplied_liquid_unheld_recent_session_data():
    records = momentum()
    records[0]["daily_pct"] = -7.999
    records[1]["volume"] -= 1
    records[3]["price_asof"] = (FRIDAY - timedelta(hours=2)).isoformat()
    assert [c["ticker"] for c in selloffs.select_candidates(records, context(), FRIDAY)] == ["CCC"]
    assert selloffs.select_candidates(records, context(), FRIDAY + timedelta(minutes=15)) == []
    assert selloffs.select_candidates(records, context(), "2026-11-27T18:00:00Z", reconstructed=True) == []
    records[2]["price_asof"] = None
    assert selloffs.select_candidates(records, context(), FRIDAY) == []
    section = selloffs.prompt_section(selloffs.select_candidates(momentum(), context(), FRIDAY))
    assert "CCC" in section and "EEE" not in section and "quarantine" in section


def test_first_review_freezes_watch_pass_omissions_and_friday_overnight_mark_separately():
    db = create_engine("sqlite://")
    snapshot(db, "r1", 1)
    snapshot(db, "r2", 2, FRIDAY + timedelta(minutes=5))
    reply = {"considered": [{"ticker":"AAA","verdict":"buy"}, {"ticker":"BBB","verdict":"watch"},
                            {"ticker":"CCC","verdict":"reject"}],
             "decisions": [{"ticker":"AAA","action":"buy"}]}
    opp.record_decisions(db, "cfg", "r1", reply, input_id=1, recorded_at=FRIDAY + timedelta(seconds=5))
    opp.record_decisions(db, "cfg", "r1", {"decisions":[{"ticker":"DDD","action":"buy"}]},
                         input_id=1,recorded_at=FRIDAY + timedelta(minutes=25))
    bars = [dict(date="2026-11-20", open=45,high=50,low=38,close=40, adjusted=True),
            dict(date="2026-11-23", open=50,high=100,low=39,close=90, adjusted=True)]
    def refresh(at):
        opp.refresh_outcomes(db, "cfg", loader=lambda *args: bars, now=at)
    refresh(MONDAY)
    with db.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM learning_opportunities WHERE eligible_for_recall")).scalar() == 0
        assert c.execute(text("SELECT COUNT(*) FROM learning_selloff_observations")).scalar() == 8
        data = selloffs.report(c,"cfg",FRIDAY-timedelta(days=1),MONDAY)
        assert {r["action"] for r in data["rows"]} == {"BUY","WATCH","PASS","NOT_ASSESSED"}
        assert len(data["recent"]) == 4
        for r in data["rows"]:
            assert r["observations"] == r["matured"] == 1
            assert r["mean_net_pct"] == pytest.approx(24.750, abs=0.001)
        before = selloffs.report(c,"cfg",FRIDAY-timedelta(days=1),FRIDAY)
        assert [r["action"] for r in before["rows"]] == ["NO_REPLY"]
        assert before["rows"][0]["pending"] == 4


def test_early_or_missing_bars_never_shift_marks_to_another_session():
    db = create_engine("sqlite://")
    snapshot(db, "r", 1)
    with db.begin() as c:
        rule = c.execute(text("SELECT * FROM learning_opportunities WHERE ticker='AAA'")).mappings().one()
        bars = [dict(date="2026-11-20",close=35,adjusted=True),dict(date="2026-11-24",open=55,adjusted=True)]
        selloffs.mark(c,rule,bars,MONDAY-timedelta(minutes=2))
        status = text("SELECT status FROM learning_selloff_observations WHERE opportunity_id=:i")
        assert c.execute(status,{"i":rule["id"]}).scalar() == "pending"
        selloffs.mark(c,rule,bars,MONDAY)
        assert c.execute(status,{"i":rule["id"]}).scalar() == "missing_data"


def test_scoped_reconstruction_matches_pre_call_snapshot_and_keeps_forward_denominator():
    db = create_engine("sqlite://")
    opp.record_snapshot(db,"cfg","r",[],input_id=252,context=context(),observed_at=FRIDAY)
    data = [{k:v for k,v in m.items() if k not in ("price_asof","volume_session")} for m in momentum()]
    with db.begin() as c:
        c.execute(text("CREATE TABLE decider_inputs(id INTEGER,config_hash TEXT,run_id TEXT,call_kind TEXT,context_json TEXT,user_prompt TEXT,raw_reply TEXT)"))
        c.execute(text("CREATE TABLE momentum_snapshots(config_hash TEXT,run_id TEXT,generated_at TEXT,momentum_data TEXT,momentum_summary TEXT)"))
        c.execute(text("INSERT INTO decider_inputs VALUES(252,'cfg','r','decide',:ctx,:prompt,:reply)"),
                  dict(ctx=json.dumps(context()),prompt="News\nRendered momentum",reply=json.dumps({"decisions":[],"considered":[{"ticker":"BBB","verdict":"watch"}]})))
        c.execute(text("INSERT INTO momentum_snapshots VALUES('cfg','r',:t,:data,'Rendered momentum')"),
                  dict(t=(FRIDAY-timedelta(minutes=3)).isoformat(),data=json.dumps(data)))
        c.execute(text("INSERT INTO momentum_snapshots VALUES('cfg','r',:t,:data,'Future data')"),
                  dict(t=(FRIDAY+timedelta(minutes=3)).isoformat(),data=json.dumps(data)))
    preview = selloffs.backfill_selloffs(db,"cfg",[252,253])
    assert preview["inserted"] == 0 and len(preview["candidates"]) == 4 and 253 in preview["skipped"]
    assert selloffs.backfill_selloffs(db,"cfg",[252],apply=True)["inserted"] == 4
    assert selloffs.backfill_selloffs(db,"cfg",[252],apply=True)["inserted"] == 0
    with db.connect() as c:
        rows = c.execute(text("SELECT DISTINCT origin,assessment FROM learning_selloff_observations")).all()
        assert set(rows) == {("reconstructed","WATCH"),("reconstructed","NOT_ASSESSED")}


def test_detail_uses_first_verdict_reason_and_only_citations_in_exact_input_version():
    from policy_graph.inputs import DDL_SQLITE
    db = create_engine("sqlite://")
    candidates = selloffs.select_candidates(momentum(), context(), FRIDAY)
    opp.record_snapshot(db, "cfg", "r", [], context=context(), observed_at=FRIDAY, input_id=252,
                        prompt_version=62, selloff_candidates=candidates)
    with db.begin() as conn:
        conn.execute(text(DDL_SQLITE))
        first_prompt = "GUIDELINE INDEX (id — title):\nDA.rule.real — Stop rule\n\nDA.rule.unserved — outside index"
        conn.execute(text("""INSERT INTO decider_inputs(id,config_hash,run_id,prompt_version,user_prompt) VALUES
            (252,'cfg','r',62,:first),(253,'cfg','r',63,'GUIDELINE INDEX (id — title):\nDA.rule.future — New')"""),
            {"first":first_prompt})
    first = FRIDAY + timedelta(seconds=2)
    opp.record_decisions(db, "cfg", "r", {"decisions": [], "considered": [
        {"ticker":"AAA","verdict":"watch","why":"Wait for a higher low.",
         "cited":["DA.rule.real","DA.rule.future","DA.rule.unserved","SA.rule.other"]}]},
        input_id=252, recorded_at=first)
    later = FRIDAY + timedelta(minutes=2)
    opp.record_decisions(db, "cfg","r",{"decisions":[
        {"ticker":"AAA","action":"buy","reason":"Retry changed its mind."},
        {"ticker":"BBB","action":"buy","reason":"First mentioned by retry.","cited":["DA.rule.real"]}]},
        input_id=252, recorded_at=later)
    with db.connect() as c:
        def recent(at):
            data = selloffs.report(c,"cfg",FRIDAY - timedelta(days=1),at)
            return {r["ticker"]:r for r in data["recent"]}
        before = recent(FRIDAY)
        assert before["AAA"]["action"] == "NO_REPLY"
        assert (before["AAA"]["reason"],before["AAA"]["cited"]) == ("",[])
        rows = recent(MONDAY)
        a, b = rows["AAA"], rows["BBB"]
        assert (a["action"],a["reason"],a["prompt_version"],a["cited"]) == (
            "WATCH","Wait for a higher low.",62,["DA.rule.real"])
        assert (b["action"],b["reason"],b["cited"]) == ("NOT_ASSESSED","",[])
