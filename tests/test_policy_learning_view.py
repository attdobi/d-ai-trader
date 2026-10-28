"""Learning-map presentation preserves revisions and does not fabricate measurements."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def js(code, data=None):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    source = 'const L=require(' + json.dumps(str(ROOT/'static/js/policy-learning.js')) + ');\n'
    source += "const d=JSON.parse(require('fs').readFileSync(0,'utf8'));\n" + code
    result = subprocess.run([NODE, '-e', source], input=json.dumps(data), text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


def test_revisions_and_retirements_are_distinct_and_source_payload_is_immutable():
    data = [
        {'key':'old','id':'DA.rule','body':'old','versions':[0,1],'x':0.2,'y':0.3},
        {'key':'new','id':'DA.rule','body':'new','versions':[2],'x':0.4,'y':0.3},
        {'key':'gone','id':'DA.lesson','body':'lesson','versions':[1],'x':0.9,'y':0.6},
        {'key':'added','id':'DA.new','body':'new rule','versions':[2],'x':0.8,'y':0.8},
    ]
    result = js("const before=JSON.stringify(d),s=L.snapshot(d,2,1);console.log(JSON.stringify({points:s.points,retired:s.retired,trails:s.trails,unchanged:before===JSON.stringify(d)}));", data)
    assert result['unchanged']
    assert [(p['id'],p['lifecycle']) for p in result['points']] == [('DA.rule','modified'),('DA.new','added')]
    assert [p['id'] for p in result['retired']] == ['DA.lesson']
    assert result['trails'][0]['from']['key'] == 'old'
    assert result['trails'][0]['to']['key'] == 'new'


def test_fixed_projection_domain_does_not_move_as_future_extreme_points_arrive():
    result = js("console.log(JSON.stringify({before:L.extent([{x:.2,y:.3},{x:.6,y:.8}],{frozen:true}),after:L.extent([{x:.2,y:.3},{x:.6,y:.8},{x:1,y:0}],{frozen:true}),raw:L.extent([{x:3,y:5},{x:null,y:null},{x:4,y:6}])}));")
    assert result['before'] == result['after'] == {'x':[0,1],'y':[0,1]}
    assert result['raw'] == {'x':[3,4],'y':[5,6]}


def test_outcomes_never_substitute_a_different_horizon_or_fabricate_pending_returns():
    result = js("const c={outcomes:{'1':{horizon:1,status:'matured',net_return_pct:0},'3':{horizon:3,status:'pending',net_return_pct:null}}}; console.log(JSON.stringify({one:L.outcomeFor(c,1),three:L.outcomeFor(c,3),five:L.outcomeFor(c,5),missing:L.returnText(null),zero:L.returnText(0)}));")
    assert result['one']['net_return_pct'] == 0
    assert result['three']['status'] == 'pending' and result['five'] is None
    assert result['missing'] == 'Pending' and result['zero'] == '0.00%'


def test_array_outcome_compatibility_and_unknown_rates():
    result = js("console.log(JSON.stringify({outcome:L.outcomeFor({outcomes:[{horizon:5,status:'matured',net_return_pct:-2}]},5),missing:L.rate(null),zero:L.rate(0),half:L.rate(.5)}));")
    assert result['outcome']['net_return_pct'] == -2
    assert result['missing'] == '—' and result['zero'] == '0.0%' and result['half'] == '50.0%'


def test_line_diff_preserves_exact_before_and_after_text():
    result = js("const diff=L.lineDiff('same\\nold\\nlast','same\\nnew\\nlast');console.log(JSON.stringify({before:diff.filter(l=>l.kind!=='added').map(l=>l.text).join('\\n'),after:diff.filter(l=>l.kind!=='removed').map(l=>l.text).join('\\n'),diff}));")
    assert result['before'] == 'same\nold\nlast' and result['after'] == 'same\nnew\nlast'
    assert {'kind':'added','text':'new'} in result['diff']
    assert {'kind':'removed','text':'old'} in result['diff']


def test_historical_evidence_remains_labeled_and_separate_from_prospective_metrics():
    data = {'opportunities':{'cases':[{'id':1,'observed_at':'2026-10-28','eligible_for_recall':True,'coverage':'prospective_screener'}], 'metrics':{'recall':None}}, 'evidence':[{'id':'input-5','observed_at':'2026-10-27','eligible_for_recall':False,'coverage':'historical_decision_log'}]}
    result = js("const before=JSON.stringify(d);console.log(JSON.stringify({cases:L.casesFor(d),same:before===JSON.stringify(d)}));",data)
    assert result['same']
    assert result['cases'][1]['eligible_for_recall'] is False
    assert result['cases'][1]['coverage'] == 'historical_decision_log'


def test_replay_selection_freezes_unique_exact_inputs_from_one_incumbent_version():
    data={'opportunities':{'cases':[
        {'id':5,'input_id':12,'prompt_version':59,'observed_at':'2026-10-28T12:00'},
        {'id':6,'input_id':12,'prompt_version':59,'observed_at':'2026-10-28T12:00'},
        {'id':7,'input_id':11,'prompt_version':58,'observed_at':'2026-10-28T11:00'},
        {'id':8,'input_id':None,'prompt_version':59,'observed_at':'2026-10-28T10:00'},
    ]},'evidence':[
        {'id':'input-10-a','input_id':10,'prompt_version':59,'observed_at':'2026-10-27T12:00'},
        {'id':'input-10-b','input_id':10,'prompt_version':59,'observed_at':'2026-10-27T12:00'},
        {'id':'input-9','input_id':9,'prompt_version':59,'observed_at':'2026-10-26T12:00'},
    ]}
    result=js("console.log(JSON.stringify({one:L.replayInputIds(d,59,1),three:L.replayInputIds(d,59,3),other:L.replayInputIds(d,58,6),absent:L.replayInputIds(d,57,3)}));",data)
    assert result['one']==[12]
    assert result['three']==[12,10,9]
    assert result['other']==[11] and result['absent']==[]


def test_replay_request_selection_is_capped_at_six_inputs():
    data={'evidence':[{'input_id':i,'prompt_version':59,'observed_at':f'2026-10-{i:02}'} for i in range(1,20)]}
    assert js("console.log(JSON.stringify(L.replayInputIds(d,59,999)));",data)==[19,18,17,16,15,14]


def test_large_text_diff_falls_back_to_exact_text_instead_of_truncating():
    assert js("console.log(JSON.stringify(L.lineDiff(Array(251).fill('x').join('\\n'),'changed')));") is None


def test_richer_prospective_case_replaces_the_same_historical_input_ticker():
    data={'opportunities':{'cases':[{'id':3,'input_id':14,'ticker':'ABC','coverage':'prospective_screener','outcomes':{'3':{'status':'matured'}}}]},'evidence':[{'id':'history-14','input_id':14,'ticker':'ABC','coverage':'historical_decision_log'},{'id':'history-15','input_id':14,'ticker':'XYZ','coverage':'historical_decision_log'}]}
    result=js("console.log(JSON.stringify(L.casesFor(d)));",data)
    assert len(result)==2
    assert result[0]['coverage']=='prospective_screener'
    assert result[0]['outcomes']['3']['status']=='matured'
    assert result[1]['ticker']=='XYZ'


def test_naive_logged_dates_are_not_silently_reinterpreted_as_utc():
    result=js("console.log(JSON.stringify({naive:L.dateText('2026-10-28T09:38:00'),utc:L.dateText('2026-10-28T16:38:00+00:00'),none:L.dateText(null)}));")
    assert result['naive']=='2026-10-28 09:38 (as logged)'
    assert '9:38 AM PT' in result['utc']
    assert result['none']=='Time not recorded'


def test_market_themes_are_multilabel_and_unassigned_text_stays_general():
    data={'items':[{'market_themes':['ai','semiconductors','ai']},{'market_themes':[]},{}]}
    result=js("console.log(JSON.stringify({themes:d.items.map(L.marketThemes),matches:d.items.map(n=>L.inMarketTheme(n,'ai')),all:d.items.map(n=>L.inMarketTheme(n,''))}));",data)
    assert result['themes']==[['ai','semiconductors'],['general'],['general']]
    assert result['matches']==[True,False,False]
    assert result['all']==[True,True,True]


def test_theme_layout_is_deterministic_and_does_not_change_frozen_embeddings():
    data={'catalog':[{'id':'ai','label':'AI'},{'id':'energy_oil','label':'Oil'},{'id':'general','label':'General'}],
          'node':{'id':'DA.rule','key':'revision1','x':.21,'y':.73,'market_themes':['ai']}}
    result=js("const before=JSON.stringify(d),a=L.themeLayout(d.catalog,900),b=L.themeLayout(d.catalog.map(t=>({...t,case_count:999})),900),box=a.groups[0];console.log(JSON.stringify({same:before===JSON.stringify(d),point:L.themePosition(d.node.id,'ai',box),revised:L.themePosition({...d.node,key:'revision2'}.id,'ai',box),geometry:a.groups.map(g=>[g.id,g.x,g.y,g.width,g.height]),later:b.groups.map(g=>[g.id,g.x,g.y,g.width,g.height]),extent:L.extent([d.node],{frozen:true}),box}));",data)
    assert result['same'] and result['point']==result['revised']
    assert result['geometry']==result['later']
    assert result['extent']=={'x':[0,1],'y':[0,1]}
    point,box=result['point'],result['box']
    assert box['x']<point['x']<box['x']+box['width']
    assert box['y']+40<point['y']<box['y']+box['height']


def test_theme_provenance_does_not_conflate_citation_or_issuer_with_a_rule_claim():
    result=js("const n={theme_evidence:[{theme_id:'ai',source:'direct_text'},{theme_id:'ai',source:'cited_case'},{theme_id:'energy_oil',source:'cited_case'}]},c={theme_evidence:[{theme_id:'ai',source:'ticker_reference'}]};console.log(JSON.stringify({direct:L.themeEvidenceLabel(n,'ai'),linked:L.themeEvidenceLabel(n,'energy_oil'),none:L.themeEvidenceLabel(n,'geopolitics_iran'),issuer:L.caseThemeEvidenceLabel(c,'ai')}));")
    assert 'rule text' in result['direct'] and 'cited cases' in result['direct']
    assert result['linked']=='Linked through version-matched cited cases'
    assert result['none']=='No explicit market topic recorded'
    assert 'no cycle catalyst or event inferred' in result['issuer']


def test_filtering_theme_observations_never_recomputes_or_mutates_global_quality():
    data={'opportunities':{'metrics':{'recall':.4,'episodes':50},'cases':[
        {'id':1,'market_themes':['ai'],'ticker':'ABC'},
        {'id':2,'market_themes':['energy_oil'],'ticker':'XYZ'}]}}
    result=js("const before=JSON.stringify(d);console.log(JSON.stringify({filtered:L.casesFor(d).filter(c=>L.inMarketTheme(c,'ai')),metrics:d.opportunities.metrics,same:before===JSON.stringify(d)}));",data)
    assert [c['id'] for c in result['filtered']]==[1]
    assert result['metrics']=={'recall':.4,'episodes':50} and result['same']


def test_learning_map_mount_keeps_theme_controls_and_metric_scope_synchronized():
    script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
const L=require(process.argv[1]);
function element(id='',tag='div') {
 const classes=new Set();
 return {id,tagName:tag,namespaceURI:'http://www.w3.org/2000/svg',children:[],attrs:{},handlers:{},dataset:{},value:'',clientWidth:900,hidden:false,disabled:false,textContent:'',
  classList:{toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
  setAttribute(k,v){this.attrs[k]=v;if(k==='data-landmark-key')this.dataset.landmarkKey=v;},
  getAttribute(k){return this.attrs[k];},
  addEventListener(type,handler){(this.handlers[type]||=[]).push(handler);},
  async fire(type){for(const fn of this.handlers[type]||[])await fn({target:this,preventDefault(){}});},
  append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},contains(){return false;},
  querySelectorAll(selector){if(selector==='select'&&id==='plReplayForm')return replaySelects;return [];},focus(){},scrollIntoView(){},
  get innerHTML(){return this.html||'';},set innerHTML(value){this.html=value;if(tag==='select'){const m=value.match(/<option value="([^"]*)"/);this.value=m?m[1]:'';}}
 };
}
const html=fs.readFileSync(process.argv[2],'utf8'),ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
const selectIds=['plLayout','plMarketTheme','plTheme','plEvidenceTheme','plHorizon','plReplayIncumbent','plReplayCandidate','plReplayCount','plReplayMode','plReplayHorizon'];
const elements=Object.fromEntries(ids.map(id=>[id,element(id,selectIds.includes(id)?'select':'div')]));
for(const [id,value] of Object.entries({plLayout:'themes',plHorizon:'3',plReplayCount:'1',plReplayMode:'full_policy',plReplayHorizon:'3',pgVersion:'60'}))elements[id].value=value;
const replaySelects=selectIds.filter(id=>id.startsWith('plReplay')).map(id=>elements[id]);
const policyTabs=['explorer','learning'].map(view=>Object.assign(element(),{dataset:{policyView:view}}));
const lensTabs=['evolution','evidence','comparison'].map(lens=>Object.assign(element(),{dataset:{learningLens:lens}}));
global.document={activeElement:null,hidden:false,querySelector:s=>s.startsWith('#')?elements[s.slice(1)]||null:s==='.pg-page'?element():null,querySelectorAll:s=>s==='[data-policy-view]'?policyTabs:s==='[data-learning-lens]'?lensTabs:[],createElementNS:(ns,tag)=>element('',tag),addEventListener(){}};
global.location={hash:'#agent=DeciderAgent&v=60&view=learning'};global.history={replaceState(){}};
const payload={agent:'DeciderAgent',selected_version:60,versions:[{version:60}],projection:{frozen:true},theme_catalog:[{id:'ai',label:'AI',case_count:1,assessed_count:1,matured_count:0},{id:'energy_oil',label:'Oil',case_count:1},{id:'general',label:'General'}],landmarks:[{id:'DA.rule',key:'rule1',title:'Known rule',body:'Use supplied evidence',field:'strategy_directives',versions:[60],x:.25,y:.75,market_themes:['ai']}],opportunities:{metrics:{horizon:3,episodes:10,recall:.5,winner_denominator:6},cases:[{id:1,ticker:'ABC',input_id:1,prompt_version:60,action:'buy',market_themes:['ai']},{id:2,ticker:'XYZ',input_id:2,prompt_version:60,action:'watch',market_themes:['energy_oil']}]}};
let calls=0;global.fetch=async()=>{calls++;return {ok:true,json:async()=>payload};};
const win={requestAnimationFrame:fn=>fn(),addEventListener(){},matchMedia:()=>({matches:false}),setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 L.mount(win);await tick();
 assert.equal(calls,1,'only read-only learning fetch on load');
 assert.ok(elements.plMap.children[0].attrs['aria-label'].startsWith('Market-theme groups'));
 const original=JSON.stringify(payload),metric=elements.plEvidenceMetrics.innerHTML;
 elements.plMarketTheme.value='ai';await elements.plMarketTheme.fire('change');
 assert.equal(elements.plEvidenceTheme.value,'ai');
 assert.ok(elements.plCases.innerHTML.includes('ABC')&&!elements.plCases.innerHTML.includes('XYZ'));
 assert.equal(elements.plEvidenceMetrics.innerHTML,metric,'theme filter must not mislabel global quality as subset quality');
 assert.ok(elements.plCoverageNote.textContent.includes('full prospective cohort, not this theme subset'));
 elements.plLayout.value='similarity';await elements.plLayout.fire('change');
 assert.ok(elements.plMap.children[0].attrs['aria-label'].startsWith('Text-similarity landscape'));
 assert.ok(elements.plProjectionNote.textContent.includes('text similarity'));
 assert.equal(JSON.stringify(payload),original,'frontend must not rewrite frozen data');
 assert.equal(calls,1,'filters must not make model or API requests');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    result=subprocess.run([NODE,'-e',script,str(ROOT/'static/js/policy-learning.js'),str(ROOT/'templates/policy_graph.html')],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr or result.stdout


def test_dense_general_theme_spans_full_row_and_points_do_not_collide():
    data={'catalog':[{'id':'ai','label':'AI'},{'id':'energy_oil','label':'Oil'},{'id':'general','label':'General'}],
          'nodes':[{'id':f'DA.rule.{i:02}','market_themes':['general']} for i in range(32)]}
    result=js("const before=JSON.stringify(d),layout=L.themeLayout(d.catalog,780,d.nodes),general=layout.groups.find(g=>g.id==='general');console.log(JSON.stringify({layout,general,points:d.nodes.map(n=>L.themePosition(n.id,'general',general)),same:before===JSON.stringify(d)}));",data)
    group=result['general']
    assert result['same']
    assert result['layout']['groups'][0]['id']=='general'
    assert group['width']==748 and group['height']>=350
    points=result['points']
    for i,a in enumerate(points):
        assert group['x']+20<a['x']<group['x']+group['width']-20
        assert group['y']+50<a['y']<group['y']+group['height']-20
        for b in points[i+1:]:
            assert (a['x']-b['x'])**2+(a['y']-b['y'])**2>=54**2-1e-6
    empty=next(g for g in result['layout']['groups'] if g['id']=='energy_oil')
    assert empty['height']==94
