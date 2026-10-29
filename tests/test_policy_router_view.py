"""The router trace distinguishes proposed selection, captured context and timing."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def js(expression, data=None):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    code='const R=require('+json.dumps(str(ROOT/'static/js/policy-router-view.js'))+');'
    code+="const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    code+='process.stdout.write(JSON.stringify('+expression+'));'
    return json.loads(subprocess.run([NODE,'-e',code],input=json.dumps(data),capture_output=True,text=True,check=True,timeout=10).stdout)


def test_timing_preserves_replay_observer_and_native_distinctions():
    out=js('d.map(R.sourceInfo)',[{'source_kind':'replay','observer':True},{'source_kind':'live','context_summary':{'timing':'post_decision'}},{'source_kind':'live'},{}])
    assert [r['key'] for r in out]==['replay','observer','live','unknown']
    assert [r['forward'] for r in out]==[False,True,True,False]
    assert 'after' in out[1]['note']


def test_selection_does_not_substitute_proposed_ids_for_what_was_actually_read():
    out=js('R.selectionFor(d)',{'status':'ok','pinned_ids':['risk.stop'],'selection':{'selected_ids':['keep','keep'],'skipped_ids':['skip'],'actual_optional_ids':['keep','skip']}})
    assert out['pinned']==['risk.stop'] and out['selected']==['keep']
    assert out['actual']==['keep','skip'] and out['actualKnown']
    assert not js('R.selectionFor(d).actualKnown',{'status':'ok','selection':{'selected_ids':['keep']}})


def test_cycles_are_filtered_by_recorded_timing_and_sorted_without_mutation():
    out=js('({all:R.filteredRuns(d).map(r=>r.id),forward:R.filteredRuns(d,"forward").map(r=>r.id),replay:R.filteredRuns(d,"replay").map(r=>r.id),original:d.map(r=>r.id)})',[
        {'id':1,'source_kind':'live'},{'id':4,'source_kind':'replay'},{'id':3,'source_kind':'observer'},{'id':2}])
    assert out=={'all':[4,3,2,1],'forward':[3,1],'replay':[4],'original':[1,4,3,2]}


def test_trial_end_is_review_time_and_never_an_activation_instruction():
    out=js('R.trialModel(d,Date.parse("2026-11-06T00:00:00Z"))',{'status':'active','starts_at':'2026-10-29T00:00:00Z','ends_at':'2026-11-05T00:00:00Z'})
    assert out['expired'] and out['progress']==1 and out['status']=='complete'
    assert out['label']=='Review before activation' and 'never enables' in out['note']
    missing=js('R.trialModel(d,0)',{'status':'active','starts_at':'2026-10-29T00:00:00','ends_at':'2026-11-05T00:00:00'})
    assert missing['progress'] is None and missing['days_remaining'] is None


def test_flow_escapes_source_text_keeps_images_unknown_and_never_claims_active_pruning():
    out=js('R.flowHTML(d)',{'status':'ok','prompt_version':61,'context_summary':{'regime':'<img onerror=bad>','summary_count':6},'selection':{'selected_ids':['one'],'skipped_ids':['two'],'actual_optional_ids':['one','two']},'pinned_ids':['risk']})
    assert '<img' not in out and '&lt;img' in out
    assert 'Unknown screenshots' in out and 'SHADOW · UNCHANGED INPUT' in out
    assert 'saved no actual input tokens' in out and '2<small>optional IDs recorded' in out


def test_node_table_uses_actual_membership_separate_from_relevance_and_escapes_ids():
    out=js('R.tableHTML(d,"skipped")',{'status':'ok','selection':{'skipped_ids':['<evil>'],'actual_optional_ids':['<evil>']},'nodes':[{'node_id':'<evil>','decisions_p':.1,'served_in_prompt':True}]})
    assert '<evil>' not in out and '&lt;evil&gt;' in out
    assert '0.100' in out and '>Yes<' in out and 'width:10.00%' in out
    assert 'Always pinned' in js('R.tableHTML(d,"pinned")',{'pinned_ids':['risk.stop']})


def test_missing_costs_and_times_never_appear_as_free_or_assumed_utc():
    out=js('({cost:R.money(null),zero:R.money(0),date:R.dateText("2026-10-29T09:11:00"),none:R.dateText(null)})')
    assert out['cost']=='Unknown' and out['zero']=='$0.00000'
    assert out['date'].endswith('(as logged)') and out['none']=='Time not recorded'


def test_third_subtab_and_passive_refresh_are_accessible_and_read_only():
    html=(ROOT/'templates/policy_graph.html').read_text()
    assert 'id="prRouterTab" role="tab"' in html and 'aria-controls="prRouter"' in html
    assert 'id="prRouter" role="tabpanel" aria-labelledby="prRouterTab" hidden' in html
    assert 'aria-label="Recorded router cycle"' in html
    assert 'js/policy-router-view.js' in html and 'css/policy-router.css' in html
    source=(ROOT/'static/js/policy-router-view.js').read_text()
    assert "state.active&&!document.hidden&&$('#prAutoRefresh').checked" in source
    assert 'Auto-refresh paused' in source
    assert "method:'POST'" not in source and 'api.openai.com' not in source


def test_mount_fetches_only_recorded_logs_and_stops_refresh_when_hidden():
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    script=r'''
const assert=require('assert'),fs=require('fs'),R=require(process.argv[1]);
function element(){return {dataset:{},hidden:false,disabled:false,checked:true,value:'all',handlers:{},textContent:'',innerHTML:'',classList:{toggle(){},remove(){}},addEventListener(t,h){(this.handlers[t]||=[]).push(h);},querySelectorAll(){return [];},setAttribute(){},async fire(t){for(const h of this.handlers[t]||[])await h({target:this});}};}
const html=fs.readFileSync(process.argv[2],'utf8'),elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],element()]));
const nodeTabs=['selected','skipped','pinned','actual'].map(bucket=>Object.assign(element(),{dataset:{routerNodes:bucket}})),docEvents={};
global.document={hidden:false,querySelector:s=>s.startsWith('#')?elements[s.slice(1)]:element(),querySelectorAll:s=>s==='[data-router-nodes]'?nodeTabs:[],addEventListener(t,h){docEvents[t]=h;}};
global.location={hash:'#agent=DeciderAgent&v=61&view=router'};
const row={id:5,status:'ok',source_kind:'live',prompt_version:61,selection:{pinned_ids:['risk'],selected_ids:['a'],skipped_ids:['b'],actual_optional_ids:['a','b']},nodes:[{node_id:'a',decisions_p:.9,served_in_prompt:true},{node_id:'b',decisions_p:.1,served_in_prompt:true}]},calls=[],timers=[];
global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>url.includes('?')?{runs:[row],totals:{live_runs:1,replay_runs:0,cost_usd:.005},trial:{status:'active'}}:{cycle:row}};};
const win={addEventListener(){},setTimeout(fn,delay){timers.push({fn,delay});return timers.length;},clearTimeout(){},matchMedia(){return {matches:false};}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{R.mount(win);await tick();await tick();assert.equal(calls.length,2);assert.equal(calls[0].url,'/api/policy-graph/router-cycles?limit=100');assert.equal(calls[1].url,'/api/policy-graph/router-cycles/5');assert.ok(calls.every(c=>!c.options.body&&!c.options.method));assert.equal(elements.prCycleDetail.hidden,false);assert.ok(elements.prFlow.innerHTML.includes('SHADOW · UNCHANGED INPUT'));assert.ok(timers.some(t=>t.delay===30000));document.hidden=true;docEvents.visibilitychange();assert.equal(calls.length,2,'hidden page does not fetch or trigger API calls');})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    out=subprocess.run([NODE,'-e',script,str(ROOT/'static/js/policy-router-view.js'),str(ROOT/'templates/policy_graph.html')],capture_output=True,text=True,timeout=10)
    assert out.returncode==0,out.stderr or out.stdout
