"""Taxonomy describes traceable observations, never approved trading lessons."""
from copy import deepcopy
from datetime import datetime
import json

import pytest
from sqlalchemy import create_engine, event, text

from policy_graph import taxonomy as X, themes as T


@pytest.fixture
def db():
    db = create_engine('sqlite://')
    with db.begin() as c:
        c.execute(text('CREATE TABLE summaries(id INTEGER PRIMARY KEY,config_hash TEXT,agent TEXT,timestamp TIMESTAMP,run_id TEXT,data TEXT)'))
        c.execute(text('CREATE TABLE agent_feedback(id INTEGER PRIMARY KEY,config_hash TEXT,analysis_timestamp TIMESTAMP,summarizer_feedback TEXT,decider_feedback TEXT)'))
    return db


def save(db, ident, body, *, cfg='cfg', at='2026-10-20 12:00:00', **extra):
    with db.begin() as c:
        c.execute(text('INSERT INTO summaries VALUES(:i,:h,\'Agent_CNBC\',:at,\'run1\',:data)'),
                  {'i':ident, 'h':cfg, 'at':at, 'data':json.dumps({'summary':{'headlines':[body], 'insights':'Dated financial report.'}, **extra})})


def test_inventory_recovers_news_and_hypotheses_without_manufacturing_a_rule(db):
    save(db, 1, 'Iran denies plans to close the Strait of Hormuz; crude oil supply risk is discussed.',
         screenshot_paths=['/private/secret.png'], ignored='must not be forwarded')
    with db.begin() as c:
        c.execute(text("INSERT INTO agent_feedback VALUES(1,'cfg','2026-10-22 12:00:00','Consider comparing oil-exposure cases.','No validated Iran rule yet.')"))
    statements=[]
    event.listen(db,'before_cursor_execute',lambda _c,_cur,statement,_params,_ctx,_many: statements.append(statement))
    inv=X.observation_inventory(db,'cfg',now=datetime(2026,10,29))
    assert inv['source_row_counts']=={'news_observation':1,'feedback_hypothesis':1}
    assert inv['topic_counts']['shipping_hormuz']['news_observations']==1
    assert inv['topic_counts']['energy']['total']==2
    assert inv['topic_counts']['geopolitics_iran']['total']==2
    assert inv['source_hash'] and inv['safe_record_count']==2
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER')) for s in statements)
    assert 'secret.png' not in json.dumps(inv) and 'must not be forwarded' not in json.dumps(inv)
    nodes=[{'id':'DA.stop','body':'Keep the active priced stop.','versions':[1]}]
    catalog,_=T.annotate(nodes,[],config_hash='cfg',observations=inv['observations'],observation_counts=inv['topic_counts'])
    cat={r['id']:r for r in catalog}
    assert nodes[0]['market_themes']==['general']
    assert cat['geopolitics_iran']['landmark_count']==cat['geopolitics_iran']['case_count']==0
    assert cat['geopolitics_iran']['observation_count']==2
    assert cat['shipping_hormuz']['parent_id']=='trade_shipping'
    assert all('not_' in row['claim_status'] for row in inv['observations'])


def test_scoped_window_total_is_independent_of_bounded_display_and_scan_cap(db):
    for i in range(1,10): save(db,i,'Iran oil report.')
    save(db,20,'Iran oil other account.',cfg='other')
    save(db,21,'Iran oil old news.',at='2025-10-20 12:00:00')
    inv=X.observation_inventory(db,'cfg',now=datetime(2026,10,29),limit=1,scan_limit=3)
    assert inv['source_row_counts']['news_observation']==9
    assert inv['scanned_row_counts']['news_observation']==3
    assert inv['topic_counts']['geopolitics_iran']['news_observations']==3
    assert len(inv['observations'])==1 and inv['truncated'] and inv['sample_truncated']


def test_source_hash_changes_for_source_text_but_not_display_limit(db):
    save(db,1,'Iran oil report.');save(db,2,'AI semiconductor report.')
    first=X.observation_inventory(db,'cfg',now=datetime(2026,10,29),limit=1)
    second=X.observation_inventory(db,'cfg',now=datetime(2026,10,29),limit=2)
    assert first['source_hash']==second['source_hash']
    with db.begin() as c: c.execute(text("UPDATE summaries SET data=:data WHERE id=1"),{'data':json.dumps({'summary':{'headlines':['Hormuz oil report.']}})})
    assert X.observation_inventory(db,'cfg',now=datetime(2026,10,29))['source_hash']!=first['source_hash']


def test_secret_shaped_text_and_unscoped_manual_feedback_are_not_forwarded(db):
    save(db,1,'Authorization: Bearer private-credential')
    save(db,2,'Iran normal report.')
    with db.begin() as c:
        c.execute(text("INSERT INTO agent_feedback VALUES(1,NULL,'2026-10-22 12:00:00','unscoped energy claim','Iran')"))
    inv=X.observation_inventory(db,'cfg',now=datetime(2026,10,29))
    body=json.dumps(inv)
    assert 'private-credential' not in body and 'unscoped energy' not in body
    assert inv['source_row_counts']['feedback_hypothesis']==0


def test_balanced_sample_retains_older_hormuz_evidence_and_budget(db):
    save(db,1,'Strait of Hormuz transit risk. Iran denies a closure.',at='2026-08-20 12:00:00')
    for i in range(2,50): save(db,i,'AI data-center growth.')
    inv=X.observation_inventory(db,'cfg',now=datetime(2026,10,29),limit=12)
    assert 'summary:1' in {row['record_id'] for row in inv['observations']}
    records=X.proposal_records(inv)
    assert sum(len(json.dumps(row,ensure_ascii=False)) for row in records)<=X.MAX_PROPOSAL_CHARS
    assert 'summary:1' in {row['record_id'] for row in records}
    assert all(set(row)=={'record_id','source_kind','source_sha256','observed_at','text'} for row in records)


def proposal(records):
    row=next(row for row in records if 'Hormuz' in row['text'])
    return {'taxonomy_version':X.VERSION,'topics':[{'id':'shipping_hormuz','parent_id':'trade_shipping','label':'Strait of Hormuz','description':'Reported Hormuz transit and disruption risks.','evidence':[{'record_id':row['record_id'],'quote':'Strait of Hormuz'}]}],'limitations':['A risk mention does not establish a closure or a profitable trading rule.']}


def test_valid_model_proposal_is_source_bound_research_and_inputs_unchanged(db):
    save(db,1,'Strait of Hormuz transit risk.')
    records=X.proposal_records(X.observation_inventory(db,'cfg',now=datetime(2026,10,29)))
    raw=proposal(records); old=deepcopy((raw,records))
    req=X.proposal_request(records)
    assert req['response_schema']['additionalProperties'] is False
    value=X.validate_proposal(raw,records)
    assert (raw,records)==old
    assert value['status']=='model_proposed_organization_not_policy'
    ref=value['topics'][0]['evidence'][0]
    assert ref['source_sha256']==records[0]['source_sha256'] and ref['source_kind']=='news_observation'


@pytest.mark.parametrize('kind',['quote','source','parent','extra','secret','cycle','duplicate','unprefixed_id','too_many'])
def test_model_cannot_forge_sources_change_existing_parent_or_add_unsafe_fields(db,kind):
    save(db,1,'Strait of Hormuz transit risk.')
    records=X.proposal_records(X.observation_inventory(db,'cfg',now=datetime(2026,10,29)))
    raw=proposal(records); row=raw['topics'][0]
    if kind=='quote': row['evidence'][0]['quote']='A verified profitable pattern'
    elif kind=='source': row['evidence'][0]['record_id']='summary:999'
    elif kind=='parent': row['parent_id']='technology'
    elif kind=='extra': row['trade_rule']='BUY all oil shares'
    elif kind=='secret': row['description']='data:image/png;base64,private'
    elif kind=='cycle': row.update(id='proposed_loop',parent_id='proposed_loop')
    elif kind=='duplicate': raw['topics'].append(deepcopy(row))
    elif kind=='unprefixed_id': row['id']='made_up_event'
    else: raw['topics']=[dict(row,id=f'proposed_topic_{i}') for i in range(13)]
    with pytest.raises(ValueError): X.validate_proposal(raw,records)


def test_generic_conflict_does_not_become_iran_and_hormuz_risk_stays_topic_only():
    found=T.matches('A military strike and sanctions raised shipping-route risk.')
    assert 'geopolitics_iran' not in found
    assert {'geopolitics_conflict','geopolitics_sanctions','trade_shipping'}<=found.keys()
    assert 'shipping_hormuz' not in found
    assert X.topic_path('memory_manufacturing')==['technology','semiconductors','memory_manufacturing']


def test_broad_energy_context_does_not_invent_an_oil_or_iran_specific_lesson():
    found=T.matches('AI data centers increase electricity and power-grid demand.')
    assert 'energy' in found and 'energy_oil' not in found and 'geopolitics_iran' not in found
