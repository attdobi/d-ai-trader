"""Explicit local refresh jobs are bounded, scoped and never leak diagnostics."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import threading
import time
from contextlib import contextmanager

import pytest

from policy_graph import atlas_jobs as J


def result(**kwargs):
    return {"projection_id":"a"*24,"method":"semantic_tsne","points":24,"pending":0,
            "reference_count":20,"local_embedding_requests":1,**kwargs}


def wait(job_id,cfg='cfg'):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        value=J.get(job_id,cfg)
        if value and value['status'] not in ('queued','running'):
            return value
        time.sleep(.005)
    pytest.fail('local test job did not finish')


@pytest.fixture
def registry(monkeypatch):
    pool=ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(J,'_jobs',{})
    monkeypatch.setattr(J,'_pool',pool)
    yield
    pool.shutdown(wait=True)


def test_async_work_is_explicit_scoped_and_public_results_are_allowlisted(registry,tmp_path):
    seen=[]
    def worker(engine,cfg,agent,root,**kwargs):
        seen.append((engine,cfg,agent,root,kwargs))
        return result(raw_prompt='secret context',credentials='sk-secret',hosted_api_requests=9)
    job=J.submit('injected-engine','cfg','DeciderAgent',tmp_path,days=30,worker=worker)
    assert job['status']=='queued' and 'config_hash' not in job
    done=wait(job['id'])
    assert seen==[('injected-engine','cfg','DeciderAgent',tmp_path.resolve(),{'is_margin_account':False,'days':30})]
    assert done['status']=='complete' and done['result']['hosted_api_requests']==0
    assert done['result']['points']==24 and 'raw_prompt' not in json.dumps(done) and 'sk-secret' not in json.dumps(done)
    assert all(datetime.fromisoformat(done[key]).tzinfo is not None for key in ['created_at','started_at','finished_at'])
    assert J.get(job['id'],'other') is None and J.get('invalid','cfg') is None
    done['result']['points']=999
    assert J.get(job['id'],'cfg')['result']['points']==24


def test_same_scoped_active_job_is_deduplicated_and_pool_is_globally_bounded(registry,tmp_path):
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def worker(_engine,cfg,agent,_root,**kwargs):
        calls.append((cfg,agent));entered.set();assert release.wait(3)
        return result()
    try:
        first=J.submit(None,'cfg','DeciderAgent',tmp_path,worker=worker)
        assert entered.wait(1)
        assert J.get(first['id'],'cfg')['status']=='running'
        duplicate=J.submit(None,'cfg','DeciderAgent',tmp_path,days=7,worker=worker)
        assert duplicate['id']==first['id'] and duplicate['days']==90
        second=J.submit(None,'cfg','SummarizerAgent',tmp_path,worker=worker)
        third=J.submit(None,'other','DeciderAgent',tmp_path,worker=worker)
        fourth=J.submit(None,'other','SummarizerAgent',tmp_path,worker=worker)
        assert all(J.get(job['id'],cfg)['status']=='queued' for job,cfg in [(second,'cfg'),(third,'other'),(fourth,'other')])
        with pytest.raises(J.AtlasJobBusy,match='atlas_queue_full'):
            J.submit(None,'third','DeciderAgent',tmp_path,worker=worker)
        assert len(calls)==1
    finally:
        release.set()
    assert wait(first['id'])['status']=='complete'
    assert wait(fourth['id'],'other')['status']=='complete'
    assert len(calls)==4


def test_failure_returns_fixed_safe_error_and_frees_the_active_pair(registry,tmp_path):
    def broken(*_args,**_kwargs):
        raise RuntimeError('postgresql://user:password@host/database data:image/png;base64,secret')
    first=J.submit(None,'cfg','DeciderAgent',tmp_path,worker=broken)
    done=wait(first['id'])
    assert done['status']=='error' and done['error_code']=='local_atlas_refresh_failed'
    assert 'password' not in json.dumps(done) and 'base64' not in json.dumps(done)
    second=J.submit(None,'cfg','DeciderAgent',tmp_path,worker=lambda *_a,**_k:result())
    assert second['id']!=first['id'] and wait(second['id'])['status']=='complete'


@pytest.mark.parametrize('cfg,agent,days,code',[
    ('../unsafe','DeciderAgent',90,'invalid_configuration'),('cfg','UnknownAgent',90,'invalid_agent'),
    ('cfg','DeciderAgent',0,'invalid_days'),('cfg','DeciderAgent',True,'invalid_days')])
def test_invalid_arguments_never_start_work(registry,tmp_path,cfg,agent,days,code):
    with pytest.raises(J.AtlasJobError,match=code):
        J.submit(None,cfg,agent,tmp_path,days=days,worker=lambda *_a,**_k:pytest.fail('invalid job started'))
    assert J._jobs=={}


def test_terminal_registry_is_bounded_and_get_never_reads_sources(registry,tmp_path,monkeypatch):
    for index in range(J.MAX_RETAINED+4):
        job=J.submit(None,'cfg','DeciderAgent',tmp_path,worker=lambda *_a,**_k:result())
        assert wait(job['id'])['status']=='complete'
    assert len(J._jobs)<=J.MAX_RETAINED
    monkeypatch.setattr(J,'_refresh',lambda *_a,**_k:pytest.fail('GET invoked refresh'))
    assert J.get(job['id'],'cfg')['result']['projection_id']=='a'*24


def test_invalid_worker_result_is_an_error_instead_of_false_completion(registry,tmp_path):
    job=J.submit(None,'cfg','DeciderAgent',tmp_path,worker=lambda *_a,**_k:{'points':10,'model_secret':'private'})
    done=wait(job['id'])
    assert done['status']=='error' and done['error_code']=='invalid_refresh_result'
    assert 'model_secret' not in done


def test_production_worker_reads_sources_only_in_worker_and_extends_locally(registry,tmp_path,monkeypatch):
    from policy_graph import service,learning,taxonomy,themes,semantic_atlas
    from policy_router import embed
    seen={}
    monkeypatch.setattr(service,'_Ctx',lambda engine,cfg,root,mode:(engine,cfg,root,mode))
    def history(ctx,agent):
        seen['thread']=threading.current_thread().name;seen['scope']=ctx
        return [{'key':'DA.rule:one','id':'DA.rule','body':'current immutable rule'}],[]
    monkeypatch.setattr(learning,'history',history)
    def inventory(_engine,cfg,**kwargs):
        seen['inventory']=(cfg,kwargs)
        return {'available':True,'observations':[{'record_id':'summary:1','text':'news'}],'topic_counts':{}}
    monkeypatch.setattr(taxonomy,'observation_inventory',inventory)
    monkeypatch.setattr(themes,'annotate',lambda *_a,**_k:None)
    @contextmanager
    def locked(path):
        seen['locked']=True;seen['path']=path
        yield
        seen['locked']=False
    monkeypatch.setattr(learning,'_locked',locked)
    monkeypatch.setattr(embed,'EmbedCache',lambda path:path)
    class Client:
        calls=2
        def __init__(self,*args,**kwargs):seen['client']=(args,kwargs)
    monkeypatch.setattr(embed,'EmbeddingClient',Client)
    def existing(*_a,**kwargs):
        assert seen['locked'];seen['existing']=kwargs
        return {'method':'semantic_tsne','point_limit':700}
    monkeypatch.setattr(semantic_atlas,'atlas_payload',existing)
    def build(landmarks,observations,path,**kwargs):
        assert seen['locked'];seen['build']=(landmarks,observations,path,kwargs)
        return {'id':'b'*24,'method':'semantic_tsne','points':[{'placement':'tsne_reference'},{'placement':'knn_extension_approximate'}],
                'pending':0,'reference_count':1,'point_limit':700}
    monkeypatch.setattr(semantic_atlas,'_build_atlas',build)
    job=J.submit('engine','cfg','DeciderAgent',tmp_path)
    done=wait(job['id'])
    assert done['status']=='complete', (done,seen)
    assert done['result']['approximate_extensions']==1
    assert seen['thread']!=threading.current_thread().name
    assert seen['scope']==('engine','cfg',tmp_path.resolve(),False)
    assert seen['inventory']==('cfg',{'days':90,'limit':120})
    assert seen['client'][0]==('http://127.0.0.1:1234/v1',embed.DEFAULT_EMBED_MODEL)
    assert seen['build'][3]['force'] is False and seen['build'][3]['allow_lexical'] is False
    assert seen['build'][3]['embedding_budget_s']==60 and seen['build'][3]['max_points']==700
    assert seen['path']==tmp_path/'agents'/'decider'/'policy-router'/'cfg'/'semantic-atlas.json'


@pytest.mark.parametrize('agent',[{},[],None,False])
def test_nontext_agents_are_fixed_validation_errors(registry,tmp_path,agent):
    with pytest.raises(J.AtlasJobError,match='invalid_agent'):
        J.submit(None,'cfg',agent,tmp_path,worker=lambda *_a,**_k:pytest.fail('invalid work started'))
