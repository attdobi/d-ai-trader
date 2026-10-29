"""Learning-map integration preserves atlas provenance and the selected history."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from sqlalchemy import create_engine, event, text

from policy_graph import learning as L
from policy_graph import semantic_atlas as A
from policy_graph import service

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def scene(data,version=1,options=None):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    code='const L=require('+json.dumps(str(ROOT/'static/js/policy-learning.js'))+');'
    code+="const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    code+='const before=JSON.stringify(d);const result=L.atlasScene(d.data,d.version,d.options);'
    code+='process.stdout.write(JSON.stringify({result,same:before===JSON.stringify(d)}));'
    result=subprocess.run([NODE,'-e',code],input=json.dumps({'data':data,'version':version,'options':options or {}}),
                          text=True,capture_output=True,check=True,timeout=10)
    return json.loads(result.stdout)


def sample():
    landmarks=[
        {'key':'risk-old','id':'DA.risk','title':'Old risk rule','body':'Old stop.','versions':[0],
         'field':'strategy_directives','tags':['risk'],'x':.01,'y':.02,'market_themes':['general']},
        {'key':'risk-current','id':'DA.risk','title':'Current risk rule','body':'Updated stop.','versions':[1,2],
         'field':'strategy_directives','tags':['risk'],'x':.03,'y':.04,'market_themes':['general']},
        {'key':'energy-rule','id':'DA.energy','title':'Energy rule','body':'An explicit oil reference.','versions':[0,1,2],
         'field':'memory','tags':['oil'],'x':.05,'y':.06,'market_themes':['energy','energy_oil']},
        {'key':'future-rule','id':'DA.future','title':'Later rule','body':'Only introduced later.','versions':[2],
         'field':'memory','tags':[],'x':.07,'y':.08,'market_themes':['general']},
        {'key':'retired-rule','id':'DA.retired','title':'Retired rule','body':'Retired text.','versions':[0],
         'field':'memory','tags':[],'x':.09,'y':.1,'market_themes':['general']},
    ]
    points=[{**row,'kind':'guideline','x':.2+i*.1,'y':.8-i*.1,
             'family_id':'policy_risk' if row['id']=='DA.risk' else 'market_energy' if row['id']=='DA.energy' else 'policy_learning',
             'neighbors':[{'key':'energy-rule','similarity':.8}]} for i,row in enumerate(landmarks)]
    points.extend([
        {'key':'news-before','id':'summary:1','kind':'news_observation','title':'Older oil report',
         'body':'Oil supply report.','observed_at':'2026-10-01T12:00:00','x':.8,'y':.2,
         'family_id':'market_energy','market_themes':['energy','energy_oil']},
        {'key':'news-later','id':'summary:2','kind':'news_observation','title':'Later Iran report',
         'body':'Iran report.','observed_at':'2026-10-02T12:00:00','x':.9,'y':.1,
         'family_id':'market_geopolitics','market_themes':['geopolitics','geopolitics_iran']},
    ])
    return {'landmarks':landmarks,'versions':[
                {'version':0,'created_at':'2026-10-01T08:00:00'},
                {'version':1,'created_at':'2026-10-02T08:00:00'},
                {'version':2,'created_at':'2026-10-03T08:00:00'}],
            'semantic_atlas':{'id':'frozen-reference','method':'semantic_tsne','points':points,
                'clusters':[{'id':'cluster-a','member_keys':[p['key'] for p in points]}],
                'taxonomy':{'families':[{'id':'policy_risk','label':'Risk & exits','color':'#ff7f99'},
                                        {'id':'market_energy','label':'Energy & supply','color':'#f4cf67'}]}}}


def test_real_atlas_coordinates_win_over_legacy_pca_and_original_data_is_immutable():
    data=sample();result=scene(data)
    assert result['same']
    risk=next(p for p in result['result']['points'] if p['key']=='risk-current')
    expected=data['semantic_atlas']['points'][1]
    assert (risk['x'],risk['y'])==(expected['x'],expected['y'])
    assert risk['neighbor_keys']==['energy-rule']
    assert data['landmarks'][1]['x']==.03


def test_old_policy_omits_future_sources_and_future_rules_even_with_history_enabled():
    result=scene(sample(),options={'includeSources':True,'includeHistory':True})['result']
    points={p['key']:p for p in result['points']}
    assert 'news-before' in points and 'news-later' not in points
    assert 'future-rule' not in points
    assert points['risk-old']['lifecycle']=='historical'
    assert points['retired-rule']['lifecycle']=='retired'
    assert 'news-later' in {p['key'] for p in result['referencePoints']}
    # The fixed reference is not presented as policy-time source evidence.
    assert result['cutoff']=='2026-10-02T08:00:00'


def test_latest_policy_can_show_current_dated_context_without_backdating_it():
    data=sample();result=scene(data,version=2)['result']
    assert result['cutoff'] is None
    assert 'news-later' in {p['key'] for p in result['points']}
    source=next(p for p in result['points'] if p['key']=='news-later')
    assert source['observed_at']=='2026-10-02T12:00:00' and source['kind']=='news_observation'


def test_aware_history_dates_compare_instants_without_discarding_offsets():
    data=sample();data['versions'][1]['created_at']='2026-10-02T21:45:00Z'
    data['semantic_atlas']['points'][-2]['observed_at']='2026-10-02T14:30:00-07:00'
    data['semantic_atlas']['points'][-1]['observed_at']='2026-10-02T14:50:00-07:00'
    keys={p['key'] for p in scene(data)['result']['points']}
    assert 'news-before' in keys and 'news-later' not in keys


def test_mixed_aware_and_naive_history_dates_are_not_silently_reinterpreted():
    data=sample();data['versions'][1]['created_at']='2026-10-02T21:45:00Z'
    data['semantic_atlas']['points'][-2]['observed_at']='2026-10-02T14:30:00'
    data['semantic_atlas']['points'][-1]['observed_at']=None
    result=scene(data)['result'];keys={p['key'] for p in result['points']}
    assert 'news-before' not in keys and 'news-later' not in keys
    assert result['ambiguousSourceTimes']==2


def test_filters_keep_reference_geometry_and_quality_cohort_exactly_intact():
    data=sample();data['opportunities']={'metrics':{'recall':None,'episodes':12},'cases':[{'ticker':'ABC'}]}
    before=deepcopy(data)
    all_points=scene(data,options={'includeHistory':True})['result']
    filtered=scene(data,options={'includeHistory':True,'familyId':'market_energy'})['result']
    assert data==before
    assert filtered['referencePoints']==all_points['referencePoints']
    bykey={p['key']:p for p in all_points['points']}
    assert {p['key'] for p in filtered['points']}=={'energy-rule','news-before'}
    assert all((p['x'],p['y'])==(bykey[p['key']]['x'],bykey[p['key']]['y']) for p in filtered['points'])
    assert filtered['trajectories']==[]


def test_capability_family_focus_remains_distinct_from_canonical_market_topics():
    data=sample()
    capability=scene(data,options={'familyId':'policy_risk'})['result']['points']
    assert {p['key'] for p in capability}=={'risk-current'}
    assert scene(data,options={'marketTheme':'policy_risk'})['result']['points']==[]
    market=scene(data,options={'marketTheme':'energy_oil'})['result']['points']
    assert {p['key'] for p in market}=={'energy-rule','news-before'}


@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE prompt_versions(id INTEGER PRIMARY KEY, config_hash TEXT,
            agent_type TEXT,version INTEGER,system_prompt TEXT,user_prompt_template TEXT,
            strategy_directives TEXT,soul TEXT,memory TEXT,description TEXT,created_by TEXT,
            is_active BOOLEAN,created_at TIMESTAMP)'''))
        for version in (0,1):
            conn.execute(text('''INSERT INTO prompt_versions VALUES(:i,'atlas-integration','DeciderAgent',:v,
                'system','template',:d,'## Mission\nSeek opportunities.','## Lessons\nKeep evidence.',
                'Test version','human',:active,:at)'''),
                {'i':version+1,'v':version,'d':'## Current Strategy\n1. PRICED KILL — Keep stop '+str(version),
                 'active':version==1,'at':'2026-10-0'+str(version+1)+' 12:00:00'})
    yield engine
    engine.dispose()


def test_get_learning_reads_only_cached_projection_without_embedding_or_fit(db,tmp_path,monkeypatch):
    from flask import Flask
    from policy_graph.routes import register_policy_graph_routes
    ctx=service._Ctx(db,'atlas-integration',tmp_path,False)
    landmarks,_=L.history(ctx,'DeciderAgent')
    root=tmp_path/'agents/decider/policy-router/atlas-integration';root.mkdir(parents=True)
    path=root/'learning-projection.json'
    artifact={'id':'legacy-frozen','format':L.FORMAT,'method':'semantic_pca','embedding_model':'saved-local-model',
              'mean':[0.,0.],'basis':[[1.,0.],[0.,1.]],'scale':[1.,1.],
              'points':{p['key']:[.13,.87] for p in landmarks}}
    path.write_text(json.dumps(artifact));original=path.read_bytes()
    monkeypatch.setattr(L,'EmbeddingClient',lambda *args,**kwargs:pytest.fail('GET created embedding client'))
    monkeypatch.setattr(L,'projection',lambda *args,**kwargs:pytest.fail('GET fitted old projection'))
    monkeypatch.setattr(A,'_fit',lambda *args,**kwargs:pytest.fail('GET fitted semantic atlas'))
    app=Flask(__name__)
    register_policy_graph_routes(app,engine=db,get_config_hash=lambda:'atlas-integration',repo_root=tmp_path,
                                 is_margin_account=False,learning_runner=lambda *_:pytest.fail('GET invoked model'))
    statements=[]
    event.listen(db,'before_cursor_execute',lambda _conn,_cur,statement,_params,_ctx,_many:statements.append(statement))
    result=app.test_client().get('/api/policy-graph/learning?agent=DeciderAgent&version=1')
    assert result.status_code==200
    payload=result.get_json()
    assert payload['projection']['id']=='legacy-frozen'
    assert all((p['x'],p['y'])==(.13,.87) for p in payload['landmarks'])
    assert payload['semantic_atlas']['method']=='unavailable'
    assert path.read_bytes()==original and not (root/'semantic-atlas.json').exists()
    assert not any(statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER')) for statement in statements)


def test_missing_legacy_cache_does_not_create_a_new_coordinate_system(tmp_path):
    landmarks=[{'key':'one','x':.7,'y':.3}]
    path=tmp_path/'missing.json'
    value=L.cached_projection(landmarks,path)
    assert value['method']=='unavailable' and value['pending']==1
    assert landmarks[0]['x'] is None and landmarks[0]['y'] is None and not path.exists()


def test_browsing_atlas_filters_and_history_never_post_or_call_a_model_and_clear_stale_inspector():
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    data=sample()
    data.update(agent='DeciderAgent',selected_version=2,theme_catalog=[{'id':'general','label':'General'},
        {'id':'energy_oil','label':'Oil / gas'}],opportunities={'metrics':{'horizon':3,'recall':None,'episodes':7}},
        projection={'frozen':True},source_observations={'observations':[]})
    script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
const L=require(process.argv[1]),payload=JSON.parse(fs.readFileSync(0,'utf8'));
let replaySelects=[];
function element(id='',tag='div') {
 const classes=new Set();
 return {id,tagName:tag,children:[],attrs:{},handlers:{},dataset:{},value:'',clientWidth:1000,checked:true,hidden:false,textContent:'',
  classList:{toggle:(x,on)=>on?classes.add(x):classes.delete(x),add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},
  setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},
  addEventListener(type,handler){(this.handlers[type]||=[]).push(handler);},
  async fire(type){for(const handler of this.handlers[type]||[])await handler({target:this,preventDefault(){}});},
  querySelectorAll(selector){return selector==='select'&&id==='plReplayForm'?replaySelects:[];},
  querySelector(){return null;},append(...values){this.children.push(...values);},insertBefore(){},
  replaceChildren(...values){this.children=values;},contains(){return false;},focus(){},scrollIntoView(){},
  get innerHTML(){return this.html||'';},set innerHTML(value){this.html=value;if(tag==='select'){const match=value.match(/<option value="([^"]*)"/);this.value=match?match[1]:'';}}
 };
}
const html=fs.readFileSync(process.argv[2],'utf8'),ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
const selects=['plLayout','plMarketTheme','plTheme','plEvidenceTheme','plHorizon','plReplayIncumbent','plReplayCandidate','plReplayCount','plReplayMode','plReplayHorizon'];
const elements=Object.fromEntries(ids.map(id=>[id,element(id,selects.includes(id)?'select':'div')]));
for(const [id,value] of Object.entries({plLayout:'atlas',plHorizon:'3',plReplayCount:'1',plReplayMode:'full_policy',plReplayHorizon:'3',pgVersion:'2'}))elements[id].value=value;
replaySelects=selects.filter(id=>id.startsWith('plReplay')).map(id=>elements[id]);
const policyTabs=['explorer','learning','router'].map(view=>Object.assign(element(),{dataset:{policyView:view}}));
const lensTabs=['evolution','evidence','comparison'].map(lens=>Object.assign(element(),{dataset:{learningLens:lens}}));
global.document={activeElement:null,hidden:false,querySelector:s=>s.startsWith('#')?elements[s.slice(1)]||null:element(),
 querySelectorAll:s=>s==='[data-policy-view]'?policyTabs:s==='[data-learning-lens]'?lensTabs:[],addEventListener(){}};
global.location={hash:'#agent=DeciderAgent&v=2&view=learning'};global.history={replaceState(){}};
const requests=[];global.fetch=async(url,options={})=>{requests.push({url,method:options.method||'GET'});assert.equal(options.method||'GET','GET');return {ok:true,json:async()=>payload};};
let callbacks,lastScene;
const win={SemanticAtlas:{mount(_target,options){callbacks=options;return {update(scene){lastScene=scene;},destroy(){},fit(){},zoomBy(){}};}},
 requestAnimationFrame:fn=>fn(),addEventListener(){},matchMedia:()=>({matches:false}),setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const original=JSON.stringify(payload);L.mount(win);await tick();
 assert.equal(requests.length,1);assert.ok(requests[0].url.startsWith('/api/policy-graph/learning?'));
 const originalRefs=JSON.stringify(lastScene.referencePoints),metrics=elements.plEvidenceMetrics.innerHTML;
 callbacks.onSelect(lastScene.points.find(p=>p.key==='news-later'));
 assert.ok(elements.plInspector.innerHTML.includes('Later Iran report'));
 elements.plSearch.value='impossible unmatched text';await elements.plSearch.fire('input');
 assert.ok(!elements.plInspector.innerHTML.includes('Later Iran report'),'filtering must clear a hidden selected source inspector');
 assert.equal(lastScene.selectedKey,null);assert.equal(lastScene.points.length,0);
 elements.plSearch.value='';await elements.plSearch.fire('input');
 callbacks.onThemeSelect('market_energy');
 assert.deepEqual(lastScene.points.map(p=>p.key).sort(),['energy-rule','news-before']);
 assert.equal(JSON.stringify(lastScene.referencePoints),originalRefs);
 elements.plAtlasSources.checked=false;await elements.plAtlasSources.fire('change');
 assert.deepEqual(lastScene.points.map(p=>p.key),['energy-rule']);
 callbacks.onThemeSelect('');elements.plTimeline.value='1';await elements.plTimeline.fire('input');
 assert.ok(!lastScene.points.some(p=>p.key==='future-rule'));
 assert.equal(elements.plEvidenceMetrics.innerHTML,metrics,'visual filtering does not recompute cohort quality');
 assert.equal(JSON.stringify(payload),original);assert.equal(requests.length,1,'browsing and filters make no additional API/model calls');
 assert.ok(requests.every(r=>r.method==='GET'));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result=subprocess.run([NODE,'-e',script,str(ROOT/'static/js/policy-learning.js'),str(ROOT/'templates/policy_graph.html')],
                          input=json.dumps(data),capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr or result.stdout
