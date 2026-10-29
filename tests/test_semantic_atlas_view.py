"""Atlas geometry is source-derived and filters do not invent positions."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def js(expression,data=None):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    code='const A=require('+json.dumps(str(ROOT/'static/js/semantic-atlas.js'))+');'
    code+="const d=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify("+expression+'));'
    return json.loads(subprocess.run([NODE,'-e',code],input=json.dumps(data),text=True,capture_output=True,check=True,timeout=10).stdout)


def test_invalid_and_duplicate_points_do_not_become_fabricated_origin_points():
    data=[{'key':'valid','x':.2,'y':.3,'kind':'news_observation'},
          {'key':'valid','x':.8,'y':.9},{'key':'null','x':None,'y':None},
          {'key':'string','x':'.4','y':'.5'},{'key':'outside','x':1.1,'y':.3},
          {'key':'missing','x':.3}]
    result=js('A.normalizePoints(d)',data)
    assert len(result)==1 and result[0]['key']=='valid'
    assert (result[0]['x'],result[0]['y'])==(.2,.3)


def test_cluster_labels_are_anchored_to_observed_density_not_a_vacant_mean():
    data={'points':[{'key':str(i),'x':x,'y':.3,'family_id':'energy','kind':'news_observation'}
                    for i,x in enumerate((.1,.105,.11,.9))],
          'taxonomy':[{'id':'energy','label':'Energy & supply','color':'#e9b66d'}]}
    result=js('({groups:A.groupClusters(d.points,d.taxonomy),original:d.points})',data)
    group=result['groups'][0]
    assert group['x'] in (.1,.105,.11) and group['x']!=group['mean']['x']
    assert group['guideline_count']==0 and group['observation_count']==4
    assert group['label']=='Energy & supply' and group['color']=='#e9b66d'
    assert result['original']==data['points']


def test_one_point_has_inspectable_density_without_becoming_a_policy_region():
    result=js('A.contourPaths(d)',[{'key':'a','x':.35,'y':.45,'kind':'news_observation'}])
    assert len(result)==4 and all(layer['paths'] for layer in result)
    for layer in result:
        for path in layer['paths']:
            assert all(0<=v<=1 for xy in path for v in xy)
            assert max(xy[0] for xy in path)-min(xy[0] for xy in path)<.30


def test_disconnected_density_islands_are_not_joined_by_a_fabricated_topic_hull():
    points=[{'key':'a','x':.15,'y':.2},{'key':'b','x':.85,'y':.8}]
    result=js('A.contourPaths(d)',points)
    assert all(len(layer['paths'])==2 for layer in result)
    for layer in result:
        assert not any(min(p[0] for p in path)<.3 and max(p[0] for p in path)>.7 for path in layer['paths'])


def test_density_geometry_is_deterministic_and_keeps_input_coordinates_immutable():
    points=[{'key':'a','x':.2,'y':.4},{'key':'b','x':.24,'y':.42},{'key':'c','x':.3,'y':.38}]
    result=js('({first:A.contourPaths(d),second:A.contourPaths(d),points:d})',points)
    assert result['first']==result['second'] and result['points']==points
    assert js('A.contourPaths(d)',[])==[]


def test_map_neighbors_exclude_self_and_sort_ties_without_reclassifying_evidence():
    points=[{'key':'selected','x':.5,'y':.5},
            {'key':'z','x':.6,'y':.5,'kind':'news_observation'},
            {'key':'a','x':.4,'y':.5,'kind':'feedback_hypothesis'},
            {'key':'far','x':.9,'y':.9}]
    result=js('A.nearestNeighbors(d[0],d,2)',points)
    assert [p['key'] for p in result]==['a','z']
    assert [p['kind'] for p in result]==['feedback_hypothesis','news_observation']


def test_fit_camera_is_finite_for_singleton_and_empty_inputs():
    result=js('({one:A.cameraForBounds(d,1000,680),empty:A.cameraForBounds([],1000,680)})',
              [{'key':'a','x':.5,'y':.5}])
    assert .55<=result['one']['k']<=4
    assert result['empty']=={'x':0,'y':0,'k':1}
    assert result['one']['x']+.5*1000*result['one']['k']==pytest.approx(500)


def test_family_camera_uses_full_reference_members_without_changing_coordinates():
    points=[{'key':'a','family_id':'energy','x':.1,'y':.2},
            {'key':'b','family_id':'energy','x':.2,'y':.3},
            {'key':'other','family_id':'technology','x':.9,'y':.8}]
    result=js('({camera:A.cameraForFamily("energy",d,1000,680),expected:A.cameraForBounds(d.slice(0,2),1000,680,82),missing:A.cameraForFamily("unknown",d,1000,680),points:d})',points)
    assert result['camera']==result['expected'] and result['missing'] is None
    assert result['points']==points and .55<=result['camera']['k']<=4


def test_paint_layers_raise_current_rules_and_selected_point_without_reordering_input():
    points=[{'key':'current','kind':'guideline','x':.5,'y':.5},
            {'key':'source','kind':'news_observation','x':.5,'y':.5},
            {'key':'old','kind':'guideline','lifecycle':'historical','x':.5,'y':.5},
            {'key':'retired','kind':'guideline','lifecycle':'retired','x':.5,'y':.5}]
    result=js('({order:A.pointPaintOrder(d).map(p=>p.key),selected:A.pointPaintOrder(d,"old").map(p=>p.key),original:d.map(p=>p.key)})',points)
    assert result['order']==['old','retired','source','current']
    assert result['selected'][-1]=='old' and result['original']==[p['key'] for p in points]


def test_pointer_selection_uses_nearest_visible_center_despite_overlapping_hit_circles():
    points=[{'key':'earnings-rule','kind':'guideline','x':.50,'y':.50},
            {'key':'nearby-lesson','kind':'guideline','x':.508,'y':.50},
            {'key':'ghost','kind':'guideline','lifecycle':'historical','x':.50,'y':.50}]
    result=js('({rule:A.nearestPointerPoint(d,{x:1100,y:580},{x:100,y:-100,k:2},1000,680),lesson:A.nearestPointerPoint(d,{x:1116,y:580},{x:100,y:-100,k:2},1000,680)})',points)
    assert result['rule']['key']=='earnings-rule'
    assert result['lesson']['key']=='nearby-lesson'


def test_labels_stay_in_view_with_separate_clusters_and_source_coordinates_unchanged():
    data=[{'id':'a','label':'Energy & supply','count':20,'x':.25,'y':.3},
          {'id':'b','label':'AI & compute','count':30,'x':.7,'y':.65}]
    result=js('({labels:A.labelLayout(d,1000,680),original:d})',data)
    assert result['original']==data
    for box in result['labels']:
        assert box['x']>=0 and box['y']>=0
        assert box['x']+box['w']<=1000 and box['y']+box['h']<=680
        assert box['y']>=130


def test_region_labels_prioritize_small_geopolitics_energy_and_do_not_cover_header():
    data=[{'id':f'policy_{i}','label':f'Policy family {i}','count':50-i,'x':.2+i*.035,'y':.1+i*.03} for i in range(13)]
    data += [{'id':'market_other','label':'Other reports','count':70,'x':.5,'y':.5},
             {'id':'market_geopolitics','label':'Geopolitics & trade','count':3,'x':.6,'y':.2},
             {'id':'market_energy','label':'Energy & supply','count':10,'x':.8,'y':.6}]
    result=js('A.labelLayout(d,834,680)',data)
    assert len(result)==11
    assert {'market_geopolitics','market_energy'} <= {r['id'] for r in result}
    assert 'market_other' not in {r['id'] for r in result}
    assert all(r['y']>=130 and r['w']>=155 for r in result)


def test_renderer_has_no_network_or_model_calls_and_reduced_motion_is_respected():
    source=(ROOT/'static/js/semantic-atlas.js').read_text()
    css=(ROOT/'static/css/semantic-atlas.css').read_text()
    assert 'fetch(' not in source and 'XMLHttpRequest' not in source
    assert 'prefers-reduced-motion: reduce' in source
    assert '@media(prefers-reduced-motion:reduce)' in css
