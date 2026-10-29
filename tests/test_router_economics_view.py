"""The router view cannot turn hypothetical token reductions into earned savings."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def js(expression, data):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    code = 'const R=require('+json.dumps(str(ROOT/'static/js/router-economics.js'))+');'
    code += "const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    code += 'process.stdout.write(JSON.stringify('+expression+'));'
    return json.loads(subprocess.run([NODE,'-e',code],input=json.dumps(data),capture_output=True,text=True,
                                     check=True,timeout=10).stdout)


def test_old_character_only_record_stays_unavailable_and_shadow_realized_zero():
    out = js('R.tiles(d)',{'status':'unavailable'})
    assert out[0]['value']=='Not captured' and 'Character differences' in out[0]['note']
    assert out[1]['value']=='$0.00000'


def test_router_fee_can_outweigh_gross_input_savings_and_output_is_not_assumed_saved():
    out = js('R.tiles(d)',{'status':'estimated','decider_model':'gpt-6.1-sol',
        'token_estimates':{'actual_served':20000,'decisions_selected':19900},
        'potential_input_reduction_pct':.5,'net_input_savings_usd_uncached_estimate':-.0028,
        'realized_input_savings_usd':0,'shadow_incremental_cost_usd':.003})
    assert out[0]['value']=='20,000' and out[1]['value']=='19,900'
    assert out[2]['value']=='−$0.00280' and 'output/reasoning' in out[2]['note']
    assert out[3]['value']=='$0.00000' and '$0.00300' in out[3]['note']


def test_unknown_cost_never_formats_as_free_and_model_text_is_escaped():
    out=js('R.render(d)',{'status':'estimated','decider_model':'<img onerror=bad>',
                         'token_estimates':{'actual_served':0,'decisions_selected':None}})
    assert '<img' not in out and '&lt;img' in out
    assert 'Unknown' in out and '$0.00000' not in out


def test_json_selection_distinguishes_unknown_answers_actual_reads_and_pinned_ids():
    out=js('R.selectionFor(d)',{'pinned_ids':['rule.stop'],'nodes':[
        {'node_id':'lesson.keep','decisions_choice':'include','served_in_prompt':False},
        {'node_id':'lesson.drop','decisions_choice':'exclude','served_in_prompt':True},
        {'node_id':'lesson.unknown','decisions_choice':None,'served_in_prompt':False}]})
    assert out=={'pinned_ids':['rule.stop'],'selected_ids':['lesson.keep'],
                 'skipped_ids':['lesson.drop'],'actual_optional_ids':['lesson.drop']}


def test_screenshot_comparisons_use_text_reduction_without_inventing_total_input_percentage():
    out=js('R.tiles(d)',{'status':'estimated','image_count':12,'token_scope':'text_only',
        'images_preserved_across_variants':True,'decider_model':'gpt-6.1-sol',
        'token_estimates':{'actual_served':20000,'decisions_selected':19900},
        'potential_input_reduction_pct':45,'text_input_reduction_pct':.5,
        'net_input_savings_usd_uncached_estimate':-.0033,'shadow_incremental_cost_usd':.0035,
        'realized_input_savings_usd':0})
    assert len(out)==5
    assert 'text input' in out[0]['label'] and 'image tokens excluded' in out[0]['note']
    assert 'text input' in out[1]['label'] and '0.50% potential text reduction' in out[1]['note']
    assert '45' not in json.dumps(out)
    assert out[2]['value']=='−$0.00330' and 'complete router fee, including its images' in out[2]['note']
    assert out[3]['value']=='$0.00000'
    assert out[4]['value']=='12 images' and 'Identical screenshots' in out[4]['note']
    assert 'Image-only tokens and cost are unavailable' in out[4]['note']


def test_missing_image_token_profile_does_not_fall_back_to_text_as_total_or_free_images():
    out=js('R.tiles(d)',{'status':'estimated','image_count':1,
        'token_estimates':{'actual_served':2000,'decisions_selected':1800},
        'potential_input_reduction_pct':10,'images_preserved_across_variants':False})
    assert 'Text reduction unknown' in out[1]['note'] and '10.00%' not in out[1]['note']
    assert out[4]['value']=='1 image' and 'not confirmed' in out[4]['note']
    assert 'no image savings are credited' in out[4]['note']
    assert '$0.00000' not in json.dumps(out)
