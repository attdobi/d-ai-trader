"""Refreshing is explicit, same-origin, config-scoped and separate from GET."""
from pathlib import Path

import pytest
from flask import Flask

from policy_graph import atlas_jobs as J
from policy_graph.routes import register_policy_graph_routes


@pytest.fixture
def app_data(tmp_path,monkeypatch):
    app=Flask(__name__)
    scope={'id':'current'};calls=[]
    def submit(engine,cfg,agent,**kwargs):
        calls.append((engine,cfg,agent,kwargs))
        return {'id':'a'*32,'job_id':'a'*32,'agent':agent,'status':'queued'}
    monkeypatch.setattr(J,'submit',submit)
    monkeypatch.setattr(J,'get',lambda ident,cfg:({'id':ident,'status':'complete','result':{'points':24}}
                        if ident=='a'*32 and cfg=='current' else None))
    monkeypatch.setattr(J,'_refresh',lambda *_a,**_k:pytest.fail('route GET ran a local model'))
    register_policy_graph_routes(app,engine='engine',get_config_hash=lambda:scope['id'],
                                 repo_root=tmp_path,is_margin_account=False)
    return app.test_client(),scope,calls,tmp_path


def test_explicit_post_uses_server_scope_and_root_ignoring_spoofed_body(app_data):
    client,_scope,calls,root=app_data
    response=client.post('/api/policy-graph/learning/atlas-refresh',json={
        'agent':'SummarizerAgent','config_hash':'another','repo_root':'/private','days':3650})
    assert response.status_code==202 and response.get_json()['status']=='queued'
    assert calls==[('engine','current','SummarizerAgent',{'repo_root':root,'is_margin_account':False,'days':90})]


def test_get_job_status_is_read_only_no_store_and_cross_scope_404(app_data):
    client,scope,calls,_root=app_data
    response=client.get('/api/policy-graph/learning/atlas-jobs/'+'a'*32)
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert response.get_json()['result']['points']==24 and calls==[]
    scope['id']='another'
    assert client.get('/api/policy-graph/learning/atlas-jobs/'+'a'*32+'?config_hash=current').status_code==404
    assert client.get('/api/policy-graph/learning/atlas-jobs/invalid').status_code==404
    assert calls==[]


def test_get_does_not_submit_and_non_get_status_methods_are_rejected(app_data):
    client,_scope,calls,_root=app_data
    assert client.get('/api/policy-graph/learning/atlas-refresh').status_code==405
    assert client.post('/api/policy-graph/learning/atlas-jobs/'+'a'*32).status_code==405
    assert calls==[]


def test_foreign_origin_and_oversized_or_invalid_requests_do_not_submit(app_data):
    client,_scope,calls,_root=app_data
    foreign=client.post('/api/policy-graph/learning/atlas-refresh',headers={'Origin':'https://another.example'},json={'agent':'DeciderAgent'})
    assert foreign.status_code==400
    assert client.post('/api/policy-graph/learning/atlas-refresh',json=['DeciderAgent']).status_code==400
    assert client.post('/api/policy-graph/learning/atlas-refresh',json={'agent':'UnknownAgent'}).status_code==400
    assert client.post('/api/policy-graph/learning/atlas-refresh',json={'agent':'DeciderAgent','padding':'x'*2100}).status_code==400
    assert calls==[]


def test_same_origin_allowed_and_queue_full_is_a_bounded_conflict(app_data,monkeypatch):
    client,_scope,calls,_root=app_data
    assert client.post('/api/policy-graph/learning/atlas-refresh',headers={'Origin':'http://localhost'},json={'agent':'DeciderAgent'}).status_code==202
    def full(*_a,**_k):raise J.AtlasJobBusy('atlas_queue_full')
    monkeypatch.setattr(J,'submit',full)
    response=client.post('/api/policy-graph/learning/atlas-refresh',json={'agent':'DeciderAgent'})
    assert response.status_code==409 and 'already queued' in response.get_json()['error']
