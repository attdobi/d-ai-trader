"""Local macro context reaches the real summary call without becoming news evidence."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from bs4 import BeautifulSoup
import pytest

import summary_event_context as sec

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


def calendar():
    calls=[]
    statuses={key:{"label":label,"next":"2026-10-28" if key=='fomc' else '2026-11-06',
        "sessions_to":0 if key=='fomc' else 7,"last":"2026-09-16","sessions_since":30,
        "release_et":"2:00 pm ET" if key=='fomc' else '8:30 am ET',"phase":"pre" if key=='fomc' else None,
        "in_window":key=='fomc',"just_printed":False} for key,label in
        [('fomc','FOMC decision'),('cpi','CPI'),('jobs','jobs report')]}
    statuses['other']=[]
    return SimpleNamespace(calls=calls,
        macro_statuses=lambda day,clock:calls.append(('statuses',day,clock)) or deepcopy(statuses),
        macro_window=lambda statuses:(True,'FOMC decision today'),
        calendar_coverage=lambda day:{'horizon_end':'2026-12-12','gaps':[{'kind':'jobs','last':'2026-12-04'}]})


def function(name, namespace):
    source=ast.parse((ROOT/'main.py').read_text())
    node=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'main.py','exec'),namespace)
    return namespace[name]


def test_frozen_local_calendar_is_macro_only_timezone_explicit_and_provenance_scoped(monkeypatch):
    monkeypatch.delenv('DAI_EVENT_CALENDAR_ENABLED',raising=False)
    local=calendar()
    context=sec.freeze_summary_calendar(NOW,calendar=local)
    assert context['as_of_utc']=='2026-10-28T17:00:00Z'
    assert context['as_of_et']=='2026-10-28T13:00:00-04:00'
    assert context['macro_window'] is True
    assert context['events']['fomc']['next']=='2026-10-28'
    assert context['events']['fomc']['phase']=='pre'
    assert not {'regime','risk_score','holdings','holdings_earnings','earnings','allowance'} & context.keys()
    assert context['evidence_role']=='provided_operator_context_not_news_observation'
    assert len(local.calls)==1
    assert sec.freeze_summary_calendar(NOW,calendar=local)['context_id']==context['context_id']
    block=sec.render_summary_calendar(context)
    assert 'operator_calendar context' in block and 'not news evidence' in block
    assert 'do not add fields' in block and 'insights word budget' in block


def test_calendar_failure_and_disabled_flag_remain_unknown_without_diagnostics(monkeypatch):
    local=SimpleNamespace(macro_statuses=lambda *_a:(_ for _ in ()).throw(RuntimeError('private provider diagnostic')))
    context=sec.freeze_summary_calendar(NOW,calendar=local)
    assert context['available'] is False and context['macro_window'] is None
    assert 'private provider diagnostic' not in json.dumps(context)+sec.render_summary_calendar(context)
    monkeypatch.setenv('DAI_EVENT_CALENDAR_ENABLED','0')
    context=sec.freeze_summary_calendar(NOW,calendar=local)
    assert context['status']=='disabled' and context['events']=={}


def test_saved_metadata_is_copied_and_drops_nonallowlisted_fields():
    context=sec.freeze_summary_calendar(NOW,calendar=calendar())
    context['private_key']='never-save'
    context['events']['fomc']['private_path']='never-save'
    metadata=sec.summary_calendar_metadata(context)
    assert 'never-save' not in json.dumps(metadata)
    metadata['events']['fomc']['next']='changed'
    assert context['events']['fomc']['next']=='2026-10-28'


def summary_functions(monkeypatch,tmp_path):
    monkeypatch.setitem(sys.modules,'prompt_manager',SimpleNamespace(get_active_prompt=lambda _agent:{
        'system_prompt':'SYSTEM {strategy_directives}','strategy_directives':'ACTIVE POLICY',
        'user_prompt_template':'Content: {content}\nFeedback: {feedback_context}',
        'version':31,'soul':'Identity','memory':'Prior evidence'}))
    calls=[]
    reply={'headlines':['A','B','C'],'insights':'Observed news.'}
    namespace={'os':os,'json':json,'re':re,'BeautifulSoup':BeautifulSoup,
        'SUMMARY_WITH_IMAGES_ONLY':False,'feedback_tracker':SimpleNamespace(get_latest_feedback=lambda:{'summarizer_feedback':'Check dated evidence'}),
        'prompt_manager':SimpleNamespace(ask_openai=lambda *args,**kwargs:calls.append((args,kwargs)) or reply,
                                       last_usage=lambda:{'cost_usd':.001,'total_tokens':20,'model':'fake-model'}),
        'RUN_DIR':str(tmp_path),'RUN_TIMESTAMP':'20261028T100000','SECOND_SHOT_SCROLL_MULTIPLIERS':{},
        'current_capture_timestamp':lambda:'20261028T100000','time':SimpleNamespace(sleep=lambda _:None),
        'try_click_popup':lambda *_a:False,'hide_blocking_overlays':lambda *_a:None}
    function('get_openai_summary',namespace)
    function('summarize_page',namespace)
    return namespace,calls,reply


def test_fake_llm_request_keeps_news_feedback_images_and_shared_calendar_and_saves_provenance(monkeypatch,tmp_path):
    namespace,calls,reply=summary_functions(monkeypatch,tmp_path)
    context=sec.freeze_summary_calendar(NOW,calendar=calendar())
    class Driver:
        window_handles=['test']
        current_url='https://example.test/news'
        page_source='<p>Original article about company earnings.</p>'
        def get(self,url):assert url==self.current_url
        def set_page_load_timeout(self,_seconds):pass
        def execute_script(self,*_a):pass
        def save_screenshot(self,path):Path(path).write_bytes(b'fake-image')
    result=namespace['summarize_page']('Source',Driver.current_url,Driver(),event_context=context)
    (args,kwargs),=calls
    assert 'Original article about company earnings.' in args[0]
    assert 'Check dated evidence' in args[0] and 'Check dated evidence' in args[1]
    assert '2026-10-28T17:00:00Z' in args[0] and 'FOMC decision: next 2026-10-28' in args[0]
    assert 'not news evidence' in args[0] and 'company earnings dates' in args[0]
    assert kwargs['agent_name']=='SummarizerAgent' and len(kwargs['image_paths'])==2
    assert result['summary'] is reply and set(reply)=={'headlines','insights'}
    assert result['operator_calendar']['context_id']==context['context_id']
    assert result['operator_calendar']['evidence_role']=='provided_operator_context_not_news_observation'


def test_standalone_summary_builds_one_macro_context(monkeypatch,tmp_path):
    namespace,calls,_reply=summary_functions(monkeypatch,tmp_path)
    context=sec.freeze_summary_calendar(NOW,calendar=calendar())
    built=[]
    monkeypatch.setattr(sec,'freeze_summary_calendar',lambda:built.append(True) or context)
    namespace['get_openai_summary']('Source','<p>News</p>',[])
    assert len(built)==len(calls)==1


@pytest.mark.parametrize('workers',[1,2])
def test_one_sweep_freezes_one_snapshot_shared_by_all_workers(monkeypatch,workers):
    context=sec.freeze_summary_calendar(NOW,calendar=calendar())
    built=[]
    monkeypatch.setattr(sec,'freeze_summary_calendar',lambda:built.append(True) or context)
    groups=[]
    def process(batch,worker_id,*,event_context):groups.append((list(batch),worker_id,event_context))
    namespace={'initialize_database':lambda:None,'SUMMARY_MAX_WORKERS':workers,
        'URLS':[(str(i),'https://example.test') for i in range(6)],'_process_agent_sequence':process,
        'ThreadPoolExecutor':ThreadPoolExecutor,'as_completed':as_completed,
        'FuturesTimeoutError':FuturesTimeoutError,'os':os}
    function('run_summary_agents',namespace)()
    assert len(built)==1 and sum(len(group[0]) for group in groups)==6
    assert all(group[2] is context for group in groups)
