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
