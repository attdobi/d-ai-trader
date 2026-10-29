"""Cycle browsing is read-only, config-scoped and cannot issue model calls."""
import json
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine,event,text

from policy_graph.routes import register_policy_graph_routes
from policy_router.decisions_log import ensure_schema


@pytest.fixture
def app_data(tmp_path,monkeypatch):
    engine=create_engine('sqlite://')
    ensure_schema(engine)
    for ident,cfg in [(1,'cfg'),(2,'other')]:
        with engine.begin() as c:
            c.execute(text('''INSERT INTO policy_router_comparisons
              (id,config_hash,run_id,prompt_version,source_kind,status,provider,model,request_attempted,
               cost_usd,nodes_json,comparison_json,pinned_json)
              VALUES(:i,:h,'run',61,'replay','ok','openai_decisions','gpt-6-luna',FALSE,
               NULL,'[]','{}','[]')'''),{'i':ident,'h':cfg})
    import policy_router.decisions as D
    import policy_graph.taxonomy as X
    def forbidden(*_a,**_k):
        pytest.fail('GET browsing must never make a model call or start a review')
    monkeypatch.setattr(D,'route_shadow_cycle',forbidden)
    monkeypatch.setattr(D,'http_transport',forbidden)
    monkeypatch.setattr(X,'proposal_request',forbidden)
    app=Flask(__name__)
    scope={'id':'cfg'}
    register_policy_graph_routes(app,engine=engine,get_config_hash=lambda:scope['id'],
                                 repo_root=tmp_path,is_margin_account=False,learning_runner=forbidden,llm=forbidden)
    statements=[]
    event.listen(engine,'before_cursor_execute',lambda _c,_cur,sql,_p,_ctx,_many:statements.append(sql))
    yield app.test_client(),scope,statements
    engine.dispose()


def test_list_and_detail_are_no_store_read_only_and_scope_comes_from_session(app_data):
    client,scope,statements=app_data
    listing=client.get('/api/policy-graph/router-cycles?limit=1&config_hash=other')
    assert listing.status_code==200 and listing.headers['Cache-Control']=='no-store'
    data=listing.get_json()
    assert [row['id'] for row in data['runs']]==[1]
    assert data['trial']['status']=='not_started'
    detail=client.get('/api/policy-graph/router-cycles/1')
    assert detail.status_code==200 and detail.headers['Cache-Control']=='no-store'
    assert detail.get_json()['id']==1
    assert client.get('/api/policy-graph/router-cycles/2').status_code==404
    scope['id']='other'
    assert client.get('/api/policy-graph/router-cycles/1').status_code==404
    assert client.get('/api/policy-graph/router-cycles/2').get_json()['id']==2
    assert not any(sql.lstrip().upper().startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for sql in statements)


@pytest.mark.parametrize('value',['0','201','-1','1.5','two','', ' 10', '1e2'])
def test_limit_rejects_invalid_bounds_before_any_database_write(app_data,value):
    client,_scope,statements=app_data
    response=client.get('/api/policy-graph/router-cycles',query_string={'limit':value})
    assert response.status_code==400 and response.get_json()=={'error':'limit must be an integer between 1 and 200'}
    assert not any(sql.lstrip().upper().startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for sql in statements)


@pytest.mark.parametrize('value',['1','100','200'])
def test_limit_accepts_declared_bounds_and_list_is_bounded(app_data,value):
    client,_scope,_statements=app_data
    response=client.get('/api/policy-graph/router-cycles',query_string={'limit':value})
    assert response.status_code==200 and len(response.get_json()['runs'])<=int(value)


def test_unknown_cycle_and_mutating_methods_are_rejected(app_data):
    client,_scope,_statements=app_data
    missing=client.get('/api/policy-graph/router-cycles/999')
    assert missing.status_code==404 and missing.get_json()=={'error':'Unknown router comparison'}
    assert client.post('/api/policy-graph/router-cycles').status_code==405
    assert client.post('/api/policy-graph/router-cycles/1').status_code==405
