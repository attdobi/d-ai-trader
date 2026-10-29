"""Taxonomy organization audits stay immutable and separate from active policy."""
from copy import deepcopy
import json

import pytest
from sqlalchemy import create_engine,event,inspect,text

from policy_graph import taxonomy as X
from policy_graph import taxonomy_review as R


@pytest.fixture
def db():
    db=create_engine('sqlite://')
    yield db
    db.dispose()


def proposal(word='Hormuz', suffix='a'):
    records=[{'record_id':'summary:1','source_kind':'news_observation','source_sha256':suffix*64,
              'text':f'{word} transit risk was reported.'}]
    raw={'taxonomy_version':X.VERSION,'topics':[{'id':'shipping_hormuz','parent_id':'trade_shipping',
        'label':'Strait of Hormuz','description':'Reported transit risks, not a verified closure.',
        'evidence':[{'record_id':'summary:1','quote':word}]}],
        'limitations':['A source report is not an approved trading lesson.']}
    return X.validate_proposal(raw,records)


def test_latest_missing_table_is_read_only_and_never_bootstraps_schema(db):
    statements=[]
    event.listen(db,'before_cursor_execute',lambda _c,_cur,statement,_p,_ctx,_many:statements.append(statement))
    assert R.latest_review(db,'cfg') is None
    assert not inspect(db).has_table('policy_taxonomy_reviews')
    assert not any(s.lstrip().upper().startswith(('CREATE','INSERT','UPDATE','DELETE','ALTER')) for s in statements)


def test_duplicate_save_returns_original_immutable_row_and_does_not_mutate_inputs(db):
    review=proposal();usage={'prompt_tokens':100,'completion_tokens':12,'total_tokens':112,
        'cached_input_tokens':0,'reasoning_tokens':0,'arbitrary':'private','invalid':-1}
    original=deepcopy((review,usage))
    first=R.save_review(db,'cfg',review,model='gpt-6.1-sol',usage=usage,cost_usd=.00032)
    changed=deepcopy(review);changed['limitations']=['A later caller cannot overwrite this immutable audit.']
    again=R.save_review(db,'cfg',changed,model='different-model',usage={'prompt_tokens':900},cost_usd=9)
    assert first==again and (review,usage)==original
    value=R.latest_review(db,'cfg')
    assert value['id']==first and value['model']=='gpt-6.1-sol' and value['cost_usd']==.00032
    assert value['limitations']==review['limitations']
    assert value['usage']=={k:v for k,v in usage.items() if k not in ('arbitrary','invalid')}
    assert value['status']=='model_proposed_organization_not_policy'
    with db.connect() as c:
        assert c.execute(text('SELECT count(*) FROM policy_taxonomy_reviews')).scalar_one()==1
    assert set(inspect(db).get_table_names())=={'policy_taxonomy_reviews'}


def test_latest_is_scoped_and_new_frozen_source_creates_a_new_review(db):
    first=R.save_review(db,'cfg',proposal(),model='gpt-6.1-sol',usage={},cost_usd=None)
    other=R.save_review(db,'other',proposal('Hormuz','b'),model='other',usage={},cost_usd=0)
    newest=R.save_review(db,'cfg',proposal('Hormuz','c'),model='gpt-6.1-sol',usage={},cost_usd=.001)
    assert newest>other>first
    assert R.latest_review(db,'cfg')['id']==newest
    assert R.latest_review(db,'other')['id']==other
    assert R.latest_review(db,'unknown') is None
    # Returned JSON is a copy rather than mutable shared audit state.
    view=R.latest_review(db,'cfg');view['topics'][0]['label']='Mutated in memory'
    assert R.latest_review(db,'cfg')['topics'][0]['label']=='Strait of Hormuz'


@pytest.mark.parametrize('cost',[float('nan'),float('inf'),-1,True,'0.01'])
def test_invalid_cost_is_rejected_without_creating_any_table(db,cost):
    with pytest.raises(ValueError,match='cost'):
        R.save_review(db,'cfg',proposal(),model='gpt-6.1-sol',usage={},cost_usd=cost)
    assert inspect(db).get_table_names()==[]


def test_invalid_scope_status_or_source_hash_cannot_be_saved(db):
    for cfg,changes in [('bad scope',{}),('cfg',{'status':'approved_policy'}),('cfg',{'source_hash':'not-frozen'})]:
        with pytest.raises(ValueError):
            R.save_review(db,cfg,{**proposal(),**changes},model='gpt-6.1-sol',usage={},cost_usd=None)
    assert inspect(db).get_table_names()==[]


def test_usage_telemetry_keeps_only_nonnegative_integer_allowlist(db):
    R.save_review(db,'cfg',proposal(),model='gpt-6.1-sol',usage={
        'prompt_tokens':100,'completion_tokens':True,'total_tokens':-1,
        'cached_input_tokens':2.5,'reasoning_tokens':0,'account_id':'private'},cost_usd=None)
    assert R.latest_review(db,'cfg')['usage']=={'prompt_tokens':100,'reasoning_tokens':0}
    assert 'private' not in json.dumps(R.latest_review(db,'cfg'))
