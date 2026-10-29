"""Operator calendar metadata cannot masquerade as independent news coverage."""
import ast
from collections import defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

import pytest
from sqlalchemy import create_engine, event, text

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,29,16,0)


@pytest.fixture
def ack_functions():
    # Load actual pure functions without config imports or operator DB access.
    names={'EVENT_MENTION_RE','EVENT_ACK_RE','summaries_name_event','decision_acknowledges_event',
           '_event_json','_summary_event_parts','_decision_event_text','_event_acknowledgment',
           '_format_event_acknowledgment'}
    tree=ast.parse((ROOT/'feedback_diagnostics.py').read_text())
    selected=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in names:
            selected.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id in names for target in node.targets):
            selected.append(node)
    namespace={'re':re,'json':json,'defaultdict':defaultdict,'text':text}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'feedback_diagnostics.py','exec'),namespace)
    return namespace


@pytest.fixture
def ledger():
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE trade_decisions (id INTEGER PRIMARY KEY,config_hash TEXT,run_id TEXT,timestamp TIMESTAMP,data TEXT)'))
        conn.execute(text('CREATE TABLE summaries (id INTEGER PRIMARY KEY,config_hash TEXT,run_id TEXT,data TEXT)'))
    yield engine
    engine.dispose()


def decision(engine,ident,run='run',cfg='active',data=None,when=NOW):
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO trade_decisions VALUES (:id,:cfg,:run,:stamp,:data)'),
            {'id':ident,'cfg':cfg,'run':run,'stamp':when,'data':json.dumps(data if data is not None else [{'reason':'Wait for evidence'}])})


def summary(engine,ident,run='run',cfg='active',data=None):
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO summaries VALUES (:id,:cfg,:run,:data)'),
            {'id':ident,'cfg':cfg,'run':run,'data':json.dumps(data if data is not None else {'summary':{'headlines':['Company product news'],'insights':'A current price move'}})})


def operator(**overrides):
    return {'available':True,'evidence_role':'provided_operator_context_not_news_observation',
            'events':{'fomc':{'next':'2026-12-09'},'cpi':{'next':'2026-11-10'}},**overrides}


def read(engine,functions):
    with engine.connect() as conn:
        return functions['_event_acknowledgment'](conn,'active',NOW-timedelta(days=30))


def test_metadata_only_event_keys_never_flag_news_or_acknowledgment(ledger,ack_functions):
    decision(ledger,1,data=[{'reason':'Wait for price confirmation','event_calendar':{'FOMC':'tomorrow'},'metadata':{'reason':'CPI soon'}}])
    summary(ledger,1,data={'summary':{'headlines':['Company product launch'],'insights':'Price is steady'},
        'operator_calendar':operator(),'FOMC':'metadata only','path':'/FOMC/earnings/report'})
    result=read(ledger,ack_functions)
    assert result['cycles']==result['provided_operator_calendar_cycles']==1
    assert result['flagged']==result['source_headline_mention_cycles']==result['model_text_mention_cycles']==0
    assert result['provided_calendar_acknowledged']==0 and result['provided_calendar_ack_rate_pct']==0
    assert result['rate_pct'] is None


def test_provided_calendar_repeated_in_insights_is_unattributed_not_source_coverage(ledger,ack_functions):
    decision(ledger,1,data=[{'kind':'considered_audit','considered':[{'ticker':'ABC','signals':'FOMC tomorrow','why':'Use the active setup gates'}]}])
    summary(ledger,1,data={'summary':json.dumps({'headlines':['Company product launch'],
        'insights':'EVENT CALENDAR: operator_calendar FOMC December 9; CPI November 10.'}),
        'operator_calendar':operator()})
    result=read(ledger,ack_functions)
    assert result['provided_operator_calendar_cycles']==result['provided_calendar_acknowledged']==1
    assert result['provided_calendar_ack_rate_pct']==100
    assert result['source_headline_mention_cycles']==result['provided_headline_mention_cycles']==0
    assert result['model_text_mention_cycles']==result['provided_unattributed_insights_cycles']==1
    assert result['legacy_cycles']==result['flagged']==result['acknowledged']==0
    report=ack_functions['_format_event_acknowledgment'](result)
    assert 'origin unattributed' in report and 'do not verify news origins' in report
    assert 'Summarizers named a dated event' not in report
    assert '0 cycles without saved summary rows' in report and '0 rows without usable model fields' in report


def test_actual_model_headline_event_remains_a_separate_unverified_mention(ledger,ack_functions):
    decision(ledger,1,data={'decisions':[{'reason':'FOMC can change the price response'}]})
    summary(ledger,1,data={'summary':{'headlines':['FOMC decision is tomorrow'],'insights':'Price response unknown'},
        'operator_calendar':operator()})
    result=read(ledger,ack_functions)
    assert result['provided_headline_mention_cycles']==result['provided_headline_acknowledged']==1
    assert result['source_headline_mention_cycles']==1 and result['flagged']==0


def test_legacy_nested_json_text_preserves_its_own_cohort_and_counts_each_cycle_once(ledger,ack_functions):
    decision(ledger,1,data=[{'reason':'Consider CPI timing'}])
    summary(ledger,1,data=json.dumps({'summary':json.dumps({'headlines':['Company update'],'insights':'CPI next week'})}))
    summary(ledger,2,data={'summary':{'headlines':['FOMC meeting next week'],'insights':'CPI is also upcoming'}})
    result=read(ledger,ack_functions)
    assert result['legacy_cycles']==result['cycles']==1
    assert result['flagged']==result['acknowledged']==1 and result['rate_pct']==100
    assert result['provided_operator_calendar_cycles']==0


def test_same_run_other_config_other_run_and_old_decision_cannot_leak(ledger,ack_functions):
    decision(ledger,1,data=[{'reason':'FOMC future context'}])
    decision(ledger,2,run='old',when=NOW-timedelta(days=40))
    decision(ledger,3,cfg='other',run='other')
    summary(ledger,1)
    for ident,run,cfg in [(2,'run','other'),(3,'unmatched','active'),(4,'old','active'),(5,'other','other')]:
        summary(ledger,ident,run=run,cfg=cfg,data={'summary':{'headlines':['FOMC decision'],'insights':'CPI'},'operator_calendar':operator()})
    statements=[]
    event.listen(ledger,'before_cursor_execute',lambda _c,_cu,statement,*_rest:statements.append(statement))
    result=read(ledger,ack_functions)
    assert result['cycles']==1 and result['flagged']==0
    assert result['provided_operator_calendar_cycles']==result['source_headline_mention_cycles']==0
    assert len(statements)==2 and all(statement.lstrip().startswith('SELECT') for statement in statements)


def test_unavailable_or_failed_summary_context_is_not_a_legacy_source(ledger,ack_functions):
    decision(ledger,1,run='failed')
    decision(ledger,2,run='disabled')
    summary(ledger,1,run='failed',data={'summary':'invalid JSON FOMC','operator_calendar':operator()})
    summary(ledger,2,run='disabled',data={'summary':{'insights':'FOMC date not shown','headlines':[]},'operator_calendar':operator(available=False)})
    result=read(ledger,ack_functions)
    assert result['operator_context_cycles']==2 and result['provided_operator_calendar_cycles']==1
    assert result['legacy_cycles']==result['flagged']==0
    assert result['unparseable_summary_rows']==1
    report=ack_functions['_format_event_acknowledgment'](result)
    assert '1 rows without usable model fields' in report and 'unknown, not failed policy use' in report


@pytest.mark.parametrize('model',[
    {},
    {'error':'Summary failed while processing FOMC metadata'},
    {'fomc':{'date':'2026-12-09'},'cpi':'metadata only'},
    {'headlines':['','  \n'],'insights':'  '},
    {'headlines':[{'FOMC':'not model prose'}],'insights':{'CPI':'metadata'}},
])
def test_empty_error_or_metadata_only_model_fields_remain_unassessed_without_losing_operator_provenance(ledger,ack_functions,model):
    decision(ledger,1)
    record={'summary':model,'operator_calendar':operator()}
    summary(ledger,1,data=record)
    parts=ack_functions['_summary_event_parts'](record)
    assert parts is not None and parts['model_valid'] is False
    assert parts['operator_context'] is True and parts['provided_calendar'] is True
    result=read(ledger,ack_functions)
    assert result['unparseable_summary_rows']==1
    assert result['operator_context_cycles']==result['provided_operator_calendar_cycles']==1
    assert result['source_headline_mention_cycles']==result['model_text_mention_cycles']==0
    assert result['legacy_cycles']==result['flagged']==0
    report=ack_functions['_format_event_acknowledgment'](result)
    assert '1 rows without usable model fields' in report and 'unknown, not failed policy use' in report


def test_no_matching_summaries_and_database_failure_are_reported_without_diagnostics(ledger,ack_functions):
    decision(ledger,1)
    result=read(ledger,ack_functions)
    assert result['cycles_without_summary_rows']==1
    assert '1 cycles without saved summary rows' in ack_functions['_format_event_acknowledgment'](result)
    assert result['rate_pct'] is None and result['provided_calendar_ack_rate_pct'] is None
    class Broken:
        def execute(self,*_args,**_kwargs):raise RuntimeError('private provider diagnostic')
    unavailable=ack_functions['_event_acknowledgment'](Broken(),'active',NOW)
    assert unavailable['available'] is False and 'private provider' not in json.dumps(unavailable)
    assert 'coverage unavailable' in ack_functions['_format_event_acknowledgment'](unavailable)
