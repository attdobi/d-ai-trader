"""Financial display contracts: missing evidence, units, cohorts and request races."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


def view(script, payload=None):
    if not Path(NODE).exists():
        pytest.skip('Node runtime unavailable')
    bootstrap = r'''
const fs=require('fs'),vm=require('vm');
const payload=JSON.parse(fs.readFileSync(0,'utf8')), elements={},charts=[];
function element(id){return elements[id]||=( {textContent:'',innerHTML:'',hidden:false,style:{},dataset:{},classList:{add(){},remove(){}},getContext(){return {};}} );}
const context={console,document:{addEventListener(){},getElementById:element,querySelector(){return null;},querySelectorAll(){return [];}},
window:{addEventListener(){}},Chart:class{constructor(_ctx,config){Object.assign(this,config);charts.push(this);} update(){} draw(){} destroy(){}},
fetchJSON:async()=>payload};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.payload=payload;
(async()=>{RESULT})().then(result=>process.stdout.write(JSON.stringify(result))).catch(error=>{console.error(error);process.exitCode=1;});
'''
    result=subprocess.run([NODE,'-e',bootstrap.replace('RESULT',script),str(ROOT/'static/js/feedback.js')],
                          input=json.dumps(payload),capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_no_sample_is_not_zero_and_fraction_units_convert_exactly_once():
    rows=view("return vm.runInContext('performanceRows(payload)',context);",{
        '7d':{'total_trades':0,'success_rate':0,'avg_profit':0},
        '14d':{'total_trades':2,'wins':0,'success_rate':0,'avg_profit':0},
        '30d':{'total_trades':2,'wins':2,'success_rate':1,'avg_profit':.02923129},
        'bad30d':{'total_trades':9,'success_rate':1}})
    assert [r['days'] for r in rows] == [30,14,7]
    assert rows[0]['rate'] == 100 and rows[0]['mean'] == pytest.approx(2.923129)
    assert rows[1]['rate'] == rows[1]['mean'] == 0
    assert rows[2]['rate'] is None and rows[2]['mean'] is None


def test_bars_show_closure_denominators_and_an_exact_utc_audit_without_fake_empty_bar():
    result=view("vm.runInContext('updatePerformanceChart(payload)',context);return {charts,summary:elements.trendWindowSummary.textContent,audit:elements.trendCohortBody.innerHTML};",{
        '7d':{'total_trades':2,'wins':2,'losses':0,'flat_trades':0,'success_rate':1,'avg_profit':.02923129,'net_gain_dollars':25.59999,
              'window':{'start':'2026-10-22T21:34:10Z','end':'2026-10-29T21:34:10Z'}},
        '30d':{'total_trades':0,'success_rate':None,'avg_profit':None}})
    rate=result['charts'][0]
    assert rate['type'] == 'bar'
    assert rate['data']['labels'] == [['Last 30d','n = 0'],['Last 7d','n = 2']]
    assert rate['data']['datasets'][0]['data'] == [None,100]
    assert rate['options']['scales']['y']['min'] == 0 and rate['options']['scales']['y']['max'] == 100
    assert '2 wins / 2 scored closures' in result['summary'] and '+$25.60' in result['summary']
    assert '2026-10-22 21:34 UTC' in result['audit'] and '2026-10-29 21:34 UTC' in result['audit']


def test_metrics_still_render_without_a_saved_feedback_review():
    result=view("await vm.runInContext('loadLatestFeedback()',context);return {charts:charts.length,rate:elements.successRate.textContent,analysis:elements.latestFeedback.innerHTML};",{
        'status':'success','latest_feedback':None,'period_analysis':{'30d':{'total_trades':2,'wins':1,'success_rate':.5,'avg_profit':.01}}})
    assert result['charts'] == 2 and result['rate'] == '50.0%'
    assert 'No recent feedback analysis' in result['analysis']


def test_feedback_review_uses_its_recorded_timestamp_and_fraction_units():
    result=view("await vm.runInContext('loadLatestFeedback()',context);return elements.latestFeedback.innerHTML;",{
        'status':'success','period_analysis':{},'latest_feedback':{'total_trades_analyzed':2,'success_rate':1,
         'avg_profit_percentage':.02923129,'analysis_timestamp':'2020-01-01T12:00:00Z','lookback_period_days':7}})
    assert '2.92%' in result and '0.03%' not in result
    assert '2020' in result and '7-day analysis' in result


def test_naive_ledger_dates_are_utc_and_unknown_or_flat_sales_do_not_start_loss_streaks():
    result=view("return vm.runInContext(`({date:feedbackDate('2026-10-29T18:32:07').toISOString(),rfc:feedbackDate('Wed, 28 Oct 2026 08:25:07 GMT').toISOString(),unknown:outcomeStreak([{sell_date:'2026-10-29T18:32:07Z',gain_loss_pct:null}]),flat:outcomeStreak([{sell_date:'2026-10-29T18:32:07Z',gain_loss_pct:0}]),wins:outcomeStreak(payload)})`,context);",[
        {'id':1,'sell_date':'2026-10-29T15:34:00Z','gain_loss_pct':2.8},
        {'id':2,'sell_date':'2026-10-29T18:32:00Z','gain_loss_pct':3.0},
        {'id':3,'sell_date':'2026-10-22T15:32:00Z','gain_loss_pct':-4.0}])
    assert result['date'] == '2026-10-29T18:32:07.000Z'
    assert result['rfc'] == '2026-10-28T08:25:07.000Z'
    assert result['unknown']['type'] == 'unscored' and result['unknown']['count'] == 0
    assert result['flat']['type'] == 'flat' and result['flat']['count'] == 0
    assert result['wins']['type'] == 'winning' and result['wins']['count'] == 2


def test_late_range_response_cannot_replace_the_selected_range():
    result=view(r'''
const pending=[];context.fetchJSON=()=>new Promise(resolve=>pending.push(resolve));
const old=vm.runInContext("selectedTrendPeriods='7,14,30,60,90';refreshPerformanceChart(selectedTrendPeriods)",context);
const current=vm.runInContext("selectedTrendPeriods='7,14,30';refreshPerformanceChart(selectedTrendPeriods)",context);
pending[1]({period_analysis:{'30d':{total_trades:2,wins:1,success_rate:.5,avg_profit:0}}});await current;
pending[0]({period_analysis:{'90d':{total_trades:99,wins:99,success_rate:1,avg_profit:1}}});await old;
return charts[0].data.labels;
''')
    assert result == [['Last 30d','n = 2']]


def test_event_chart_keeps_unknown_and_flat_sales_out_of_winning_markers():
    result=view("await vm.runInContext('loadEventRiskChart()',context);return charts[0].data.datasets.map(d=>({label:d.label,data:d.data}));",{
        'series':[{'date':'2026-10-29','score':55,'level':'HIGH','regime':'RISK-OFF'}],
        'trades':[{'date':'2026-10-29','action':'sell','ticker':'UNKNOWN','pct':None},
                  {'date':'2026-10-29','action':'sell','ticker':'FLAT','pct':0}]})
    values={r['label']:r['data'] for r in result}
    assert values['Sell (win)'] == [None]
    assert values['Sell (flat)'] == values['Sell (unscored)'] == [55]


@pytest.mark.parametrize('function', ['loadBenchmarkChart','loadEventRiskChart'])
def test_slower_chart_range_cannot_override_newer_selection(function):
    script=r'''
const pending=[];context.fetchJSON=()=>new Promise(resolve=>pending.push(resolve));
const old=vm.runInContext('FUNCTION(30)',context),current=vm.runInContext('FUNCTION(365)',context);
const result=date=> FUNCTION_KIND==='benchmark' ? {series:{dates:[date],portfolio:[100]},stats:{portfolio:{return_pct:0},benchmarks:{},trade:{}}}
 : {series:[{date,score:55,regime:'RISK-OFF',level:'HIGH'}]};
pending[1](result('2026-10-29'));await current;
pending[0](result('2026-09-01'));await old;
return {count:charts.length,labels:charts[0].data.labels};
'''.replace('FUNCTION_KIND',json.dumps('benchmark' if function=='loadBenchmarkChart' else 'event')).replace('FUNCTION',function)
    result=view(script)
    assert result == {'count':1,'labels':['2026-10-29']}
