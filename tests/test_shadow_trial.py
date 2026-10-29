"""Trial windows and fee reservations are not permission to route or trade."""
from datetime import datetime,timedelta,timezone
import json

import pytest
from sqlalchemy import create_engine,text

from policy_router import shadow_trial as T
from policy_router.decisions_log import cycle_detail, comparison_panel

NOW=datetime(2026,10,29,18,0,tzinfo=timezone.utc)
CFG='trial-test'

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE decider_inputs(id INTEGER PRIMARY KEY,config_hash TEXT,call_kind TEXT)'))
        c.execute(text("INSERT INTO decider_inputs VALUES(1,:h,'decide')"),{'h':CFG})
    T.ensure_schema(engine)
    yield engine
    engine.dispose()


def source(db,ident=2,cfg=CFG,kind='decide'):
    with db.begin() as c:
        c.execute(text('INSERT INTO decider_inputs VALUES(:i,:h,:k)'),{'i':ident,'h':cfg,'k':kind})


def logged(db,ident=1,source_id=2,cfg=CFG,kind='live',at='2026-10-29 11:01:00',cost=.005,attempt=True):
    with db.begin() as c:
        c.execute(text('''INSERT INTO policy_router_comparisons(id,config_hash,run_id,prompt_version,source_input_id,
            source_kind,decided_at,status,provider,model,request_attempted,cost_usd,nodes_json,comparison_json,pinned_json)
            VALUES(:i,:h,'run',61,:si,:k,:at,'ok','openai_decisions','gpt-6-luna',:a,:c,'[]','{}','[]')'''),
            {'i':ident,'h':cfg,'si':source_id,'k':kind,'at':at,'a':attempt,'c':cost})


def test_start_is_idempotent_and_has_explicit_utc_week_watermark(db):
    result=T.start_trial(db,CFG,now=NOW)
    assert result['active'] and result['mode']=='shadow' and not result['auto_promote']
    assert result['after_input_id']==1 and result['ends_at']==(NOW+timedelta(days=7)).isoformat()
    again=T.start_trial(db,CFG,now=NOW+timedelta(days=2))
    assert result['id']==again['id'] and result['ends_at']==again['ends_at']
    done=T.trial_status(db,CFG,now=NOW+timedelta(days=7))
    assert done['status']=='completed' and not done['active'] and done['remaining_seconds']==0
    assert T.start_trial(db,CFG,now=NOW+timedelta(days=8))['id']==result['id']
    assert T.start_trial(db,CFG,now=NOW+timedelta(days=8),restart=True)['id']!=result['id']


def test_report_counts_native_after_watermark_in_declared_local_window_only(db):
    T.start_trial(db,CFG,now=NOW)
    source(db)
    logged(db)
    logged(db,2,kind='replay')
    logged(db,3,cfg='another')
    logged(db,4,source_id=1)
    logged(db,5,at='2026-10-29 10:59:59')
    logged(db,6,at='2026-11-05 10:00:00') # end is 10AM after DST, not 11AM
    result=T.trial_status(db,CFG,now=NOW+timedelta(minutes=2))
    assert result['cycles']==1 and result['native_cycles']==1 and result['cost_usd']==.005
    assert result['unreserved_native_calls']==1
    assert result['realized_input_savings_usd']==0 and result['quality_status']=='unmeasured'
    assert T.trial_status(db,'another',now=NOW)['status']=='not_started'
    assert cycle_detail(db,'another',1) is None
    assert cycle_detail(db,CFG,1)['source_input_id']==2
    listing=T.cycle_list(db,CFG,limit=10,now=NOW)
    assert listing['trial']['id']==result['id'] and listing['totals']['replay_runs']==1


def test_claims_are_scoped_once_and_never_catch_up_or_cross_expiry(db):
    T.start_trial(db,CFG,now=NOW)
    source(db);source(db,3,cfg='other');source(db,4,kind='citation_repair')
    assert T.reserve_cycle(db,CFG,1,cost_bound_usd=.01,now=NOW) is None
    assert T.reserve_cycle(db,CFG,3,cost_bound_usd=.01,now=NOW) is None
    assert T.reserve_cycle(db,CFG,4,cost_bound_usd=.01,now=NOW) is None
    assert T.reserve_cycle(db,CFG,2,cost_bound_usd=.06,now=NOW) is None
    claim=T.reserve_cycle(db,CFG,2,cost_bound_usd=.02,now=NOW)
    assert claim and T.reserve_cycle(db,CFG,2,cost_bound_usd=.02,now=NOW) is None
    source(db,5)
    assert T.reserve_cycle(db,CFG,5,cost_bound_usd=.02,now=NOW+timedelta(days=7)) is None
    assert T.reserve_cycle(db,CFG,5,cost_bound_usd=.02,now=NOW-timedelta(seconds=1)) is None
    assert T.trial_status(db,CFG,now=NOW)['reserved_cost_usd']==.02


def test_known_fee_settles_once_unknown_fee_keeps_reserve_and_no_duplicate_call(db):
    T.start_trial(db,CFG,now=NOW,budget_usd=.05,max_call_usd=.03)
    source(db);source(db,3);source(db,4)
    first=T.reserve_cycle(db,CFG,2,cost_bound_usd=.03,now=NOW)
    assert T.reserve_cycle(db,CFG,3,cost_bound_usd=.03,now=NOW) is None
    logged(db,cost=.005)
    assert T.complete_cycle(db,CFG,first,comparison_id=1,cost_usd=.005,now=NOW)
    assert not T.complete_cycle(db,CFG,first,cost_usd=0,now=NOW)
    second=T.reserve_cycle(db,CFG,3,cost_bound_usd=.03,now=NOW)
    assert second
    assert T.complete_cycle(db,CFG,second,cost_usd=None,diagnostic='request_failed',now=NOW)
    result=T.trial_status(db,CFG,now=NOW)
    assert result['reserved_cost_usd']==.03 and result['committed_budget_usd']==pytest.approx(.035)
    assert T.reserve_cycle(db,CFG,4,cost_bound_usd=.02,now=NOW) is None
    assert T.reserve_cycle(db,CFG,3,cost_bound_usd=.01,now=NOW) is None


def test_skipped_request_releases_budget_but_does_not_allow_retry(db):
    T.start_trial(db,CFG,now=NOW)
    source(db)
    claim=T.reserve_cycle(db,CFG,2,cost_bound_usd=.02,now=NOW)
    T.complete_cycle(db,CFG,claim,request_attempted=False,diagnostic='request_not_sent',now=NOW)
    assert T.trial_status(db,CFG,now=NOW)['reserved_cost_usd']==0
    assert T.reserve_cycle(db,CFG,2,cost_bound_usd=.02,now=NOW) is None
    stopped=T.stop_trial(db,CFG,now=NOW+timedelta(hours=1))
    assert stopped['status']=='stopped'
    source(db,3)
    assert T.reserve_cycle(db,CFG,3,cost_bound_usd=.02,now=NOW+timedelta(hours=2)) is None


def test_already_recorded_native_prevents_observer_billing_and_settlement_checks_scope(db):
    T.start_trial(db,CFG,now=NOW)
    source(db);source(db,3)
    logged(db)
    assert T.reserve_cycle(db,CFG,2,cost_bound_usd=.02,now=NOW) is None
    claim=T.reserve_cycle(db,CFG,3,cost_bound_usd=.02,now=NOW)
    with pytest.raises(T.TrialError,match='comparison_scope'):
        T.complete_cycle(db,CFG,claim,comparison_id=1,cost_usd=.005,now=NOW)
    assert T.complete_cycle(db,'another',claim,cost_usd=.005,now=NOW) is False


@pytest.mark.parametrize('kwargs',[{'days':8},{'budget_usd':float('nan')},{'budget_usd':0},{'max_call_usd':3},
                                  {'source_timezone':'Not/A/Zone'},{'now':datetime(2026,10,29)}])
def test_invalid_trial_arguments_never_start(db,kwargs):
    with pytest.raises(T.TrialError):
        T.start_trial(db,CFG,**{'now':NOW,**kwargs})


def test_context_metadata_excludes_balances_payloads_and_cross_config_source(db):
    from types import SimpleNamespace
    from policy_router.decisions_log import record_shadow
    from policy_router.nodes import RouterNode
    from policy_router.select import select_subgraph
    node=RouterNode('DA.ltm.4','ltm','A source lesson',15,meta={'title':'Readable lesson'})
    result=SimpleNamespace(selection=select_subgraph([(node.node_id,node.kind,.9,node.chars)]),nodes={'DA.ltm.4':node},
        pinned_ids=['DA.rule.stop'],image_manifest={},usage={},status='ok',provider='openai_decisions',model='gpt-6-luna',
        policy_hash='',question_hash='',request_hash='',response_id=None,request_attempted=False,cost_usd=None,
        latency_ms=1,note='Shadow')
    ident=record_shadow(db,CFG,61,'run',result,source_kind='observer',
        context_summary={'holdings':['MSFT','12345678','bad ticker'],'regime':'RISK-OFF',
                         'summary_count':6,'cash':999,'account_id':'private','image_url':'data:image/png;base64,private',
                         'actual_decider_received_images':False,'actual_decider_image_count':0})
    detail=cycle_detail(db,CFG,ident)
    assert detail['context_summary']=={'holdings':['MSFT'],'regime':'RISK-OFF','summary_count':6,
        'actual_decider_received_images':False,'actual_decider_image_count':0,
        'entities':[],'news':[],'quarantined':[],'trend':[],'watchlist':[]}
    assert detail['nodes'][0]['title']=='Readable lesson'
    assert 'private' not in json.dumps(detail)
    assert comparison_panel(db,CFG)['totals']['observer_runs']==1
    assert cycle_detail(db,'other',ident) is None


def test_unknown_native_fee_remains_unknown_and_consumes_conservative_budget(db):
    T.start_trial(db,CFG,now=NOW,budget_usd=.05,max_call_usd=.03)
    source(db);source(db,3)
    logged(db,cost=None)
    result=T.trial_status(db,CFG,now=NOW)
    assert result['cost_usd'] is None and result['unknown_cost_calls']==1
    assert result['committed_budget_usd']==.03 and result['remaining_budget_usd']==pytest.approx(.02)
    assert T.reserve_cycle(db,CFG,3,cost_bound_usd=.03,now=NOW) is None


def test_concurrent_first_start_serializes_before_a_trial_row_exists(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    uri='sqlite:///'+str(tmp_path/'concurrent-trial.db')
    first=create_engine(uri);second=create_engine(uri)
    with first.begin() as c:
        c.execute(text('CREATE TABLE decider_inputs(id INTEGER PRIMARY KEY,config_hash TEXT,call_kind TEXT)'))
        c.execute(text("INSERT INTO decider_inputs VALUES(1,:h,'decide')"),{'h':CFG})
    T.ensure_schema(first)
    barrier=Barrier(2)
    def start(engine):
        barrier.wait(timeout=5)
        return T.start_trial(engine,CFG,now=NOW)['id']
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.map(start,[first,second])
        assert a==b
        with first.connect() as c:
            assert c.execute(text('SELECT COUNT(*) FROM policy_router_shadow_trials')).scalar_one()==1
    finally:
        first.dispose();second.dispose()
