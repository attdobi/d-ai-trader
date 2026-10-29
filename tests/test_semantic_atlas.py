"""Atlas fitting is explicit, genuine, scoped and stable across policy playback."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from policy_graph import semantic_atlas as A

CFG='atlas-test'
AGENT='DeciderAgent'


def landmarks(count=16):
    groups=['energy','technology','risk','evidence']
    return [{'key':f'DA.rule{i}:revision','id':f'DA.rule{i}', 'title':groups[i%4]+' rule',
             'body':f'{groups[i%4]} principle {i}', 'versions':[0,1],
             'market_themes':['energy' if i%4==0 else 'technology' if i%4==1 else 'general']}
            for i in range(count)]


def observation(ident=1,body='[XOM] Oil supply reported lower'):
    return {'record_id':f'summary:{ident}','source_kind':'news_observation','text':body,
            'source_agent':'Agent_CNBC','observed_at':'2026-10-29T10:00:00',
            'market_themes':['energy'],'claim_status':'recorded_report_not_independently_verified',
            'raw_prompt':'never copied','account_balance':9999}


class Embeddings:
    model='local-test-embeddings'
    base_url='http://127.0.0.1:1234/v1'
    def __init__(self): self.calls=0
    def embed(self,texts,**kwargs):
        self.calls+=1
        rows=[]
        for text in texts:
            rng=np.random.default_rng(int(hashlib.sha256(text.encode()).hexdigest()[:8],16))
            vector=rng.uniform(.001,.03,8)
            group=next((i for i,word in enumerate(['energy','technology','risk','evidence']) if word in text),0)
            vector[group]+=1
            rows.append(vector)
        return np.asarray(rows)


def simple_fit(vectors):
    n=len(vectors)
    return np.column_stack((np.arange(n),np.arange(n)%4)),np.arange(n)%4,{'projection_algorithm':'tsne','perplexity':2,'kl_divergence':.1}


def build(tmp_path,monkeypatch,rows=None,obs=None,**kwargs):
    monkeypatch.setattr(A,'_fit',simple_fit)
    return A.build_atlas(rows or landmarks(),obs or [],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,
                         embedder=kwargs.pop('embedder',Embeddings()),**kwargs)


def test_read_is_fast_no_inference_no_mutation_and_sources_keep_dates(tmp_path,monkeypatch):
    rows=landmarks();obs=[observation()];before=json.dumps([rows,obs],sort_keys=True)
    path=tmp_path/'atlas.json'
    missing=A.atlas_payload(rows,obs,path,config_hash=CFG,agent=AGENT)
    assert missing['method']=='unavailable' and missing['pending']==17 and not path.exists()
    result=build(tmp_path,monkeypatch,rows,obs)
    monkeypatch.setattr(A,'_fit',lambda *_:pytest.fail('read refitted'))
    loaded=A.atlas_payload(rows,obs,path,config_hash=CFG,agent=AGENT)
    assert loaded==result and json.dumps([rows,obs],sort_keys=True)==before
    source=next(p for p in loaded['points'] if p['kind']=='news_observation')
    assert source['record_id']=='summary:1' and source['observed_at']=='2026-10-29T10:00:00'
    assert source['versions']==[] and 'raw_prompt' not in source and 'account_balance' not in source
    assert all('vector' not in point for point in loaded['points'])


def test_extension_uses_immutable_reference_neighbors_without_refitting(tmp_path,monkeypatch):
    embedder=Embeddings();rows=landmarks()
    first=build(tmp_path,monkeypatch,rows,embedder=embedder)
    old={p['key']:(p['x'],p['y']) for p in first['points']}
    monkeypatch.setattr(A,'_fit',lambda *_:pytest.fail('extension refitted'))
    extended=rows+[{'key':'DA.new:rev','id':'DA.new','body':'energy new principle','versions':[2]}]
    result=A.build_atlas(extended,[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,embedder=embedder)
    assert result['id']==first['id'] and result['reference_count']==16
    assert all((p['x'],p['y'])==old[p['key']] for p in result['points'] if p['key'] in old)
    assert result['points'][-1]['placement']=='knn_extension_approximate' and embedder.calls==2
    assert len(result['points'][-1]['neighbors'])==6


def test_original_embedding_neighbors_are_not_inferred_from_2d_or_taxonomy(tmp_path,monkeypatch):
    result=build(tmp_path,monkeypatch)
    point=result['points'][0];by_key={p['key']:p for p in result['points']}
    closest=by_key[point['neighbors'][0]['key']]
    assert 'energy' in closest['body']
    assert point['neighbors'][0]['similarity']>.95


def test_other_config_never_loads_artifact_and_model_drift_requires_refit(tmp_path,monkeypatch):
    build(tmp_path,monkeypatch)
    assert A.atlas_payload(landmarks(),[],tmp_path/'atlas.json',config_hash='another',agent=AGENT)['method']=='unavailable'
    changed=Embeddings();changed.model='other-local-model'
    rows=landmarks()+[{'key':'DA.new','id':'DA.new','body':'risk extra','versions':[2]}]
    with pytest.raises(A.AtlasUnavailable,match='model_changed'):
        A.build_atlas(rows,[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,embedder=changed)
    rows=landmarks();rows[0]['body']='changed under an immutable key'
    with pytest.raises(A.AtlasUnavailable,match='source_key_changed'):
        A.build_atlas(rows,[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,embedder=Embeddings())


def test_loopback_only_embeddings_and_explicit_lexical_fallback(tmp_path,monkeypatch):
    remote=Embeddings();remote.base_url='https://example.com/v1'
    with pytest.raises(A.AtlasUnavailable,match='loopback'):
        build(tmp_path,monkeypatch,embedder=remote)
    with pytest.raises(A.AtlasUnavailable,match='embeddings_unavailable'):
        A.build_atlas(landmarks(),[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT)
    result=A.build_atlas(landmarks(),[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,allow_lexical=True)
    assert result['method']=='lexical_tsne' and 'not semantic embeddings' in result['note']


def test_unsafe_source_text_and_unknown_fields_never_enter_public_points():
    assert A.source_points([], [observation(body='data:image/png;base64,payload')])==[]
    assert A.source_points([{'key':'x','id':'x','body':'Authorization: Bearer secret'}],[])==[]
    point=A.source_points([], [observation()])[0]
    assert 'raw_prompt' not in point and 'account_balance' not in point


def test_source_content_revision_has_a_new_key_and_headlines_dominate_news_embedding():
    first=A.source_points([], [observation()])[0]
    changed=A.source_points([], [observation(body='[XOM] Oil supply revised')])[0]
    assert first['key']!=changed['key']
    source=observation(body='[XOM] Oil supply lower\n[CVX] Energy context\nRepeated NOT_SHOWN technical checklist')
    point=A.source_points([], [source])[0]
    assert 'NOT_SHOWN' not in A.embedding_text(point) and 'Oil supply' in A.embedding_text(point)


def test_actual_seeded_tsne_is_finite_reproducible_and_has_real_clusters(tmp_path):
    pytest.importorskip('sklearn')
    first=A.build_atlas(landmarks(),[],tmp_path/'first.json',config_hash=CFG,agent=AGENT,embedder=Embeddings())
    second=A.build_atlas(landmarks(),[],tmp_path/'second.json',config_hash=CFG,agent=AGENT,embedder=Embeddings())
    assert first['method']=='semantic_tsne' and first['fitted_with']['projection_algorithm']=='tsne'
    assert first['id']==second['id'] and first['fitted_with']['kl_divergence']>=0
    assert [(p['x'],p['y']) for p in first['points']]==[(p['x'],p['y']) for p in second['points']]
    assert len(first['clusters'])>=2
    assert all(0<=p['x']<=1 and 0<=p['y']<=1 for p in first['points'])


def test_point_cap_leaves_missing_sources_pending_and_never_silently_expands(tmp_path,monkeypatch):
    first=build(tmp_path,monkeypatch,max_points=5)
    assert len(first['points'])==5 and first['pending']==11 and first['point_limit']==5
    again=A.build_atlas(landmarks(),[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,embedder=Embeddings(),max_points=5)
    assert len(again['points'])==5 and again['id']==first['id'] and again['pending']==11
    with pytest.raises(A.AtlasUnavailable,match='smaller_point_cap'):
        A.build_atlas(landmarks(),[],tmp_path/'atlas.json',config_hash=CFG,agent=AGENT,embedder=Embeddings(),max_points=4)


def test_tiny_corpus_truthfully_reports_pca_instead_of_calling_it_tsne(tmp_path):
    pytest.importorskip('sklearn')
    result=A.build_atlas(landmarks(1),[],tmp_path/'tiny.json',config_hash=CFG,agent=AGENT,embedder=Embeddings())
    assert result['method']=='semantic_pca_small' and result['fitted_with']['projection_algorithm']=='small_corpus_pca'
    assert result['points'][0]['x']==result['points'][0]['y']==.5


def test_corrupt_or_nonfinite_cached_vectors_are_unavailable_not_used(tmp_path,monkeypatch):
    build(tmp_path,monkeypatch)
    path=tmp_path/'atlas.json';raw=json.loads(path.read_text())
    raw['points'][next(iter(raw['points']))]['vector']=[float('nan')]
    path.write_text(json.dumps(raw))
    result=A.atlas_payload(landmarks(),[],path,config_hash=CFG,agent=AGENT)
    assert result['method']=='unavailable' and not result['points'] and result['pending']==16
