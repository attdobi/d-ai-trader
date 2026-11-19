import hashlib
import json

from flask import Flask
from sqlalchemy import create_engine, inspect, text

from policy_graph.routes import register_policy_graph_routes
from policy_router.decisions_log import ensure_schema
from policy_router.usefulness import TABLE


def dashboard(tmp_path):
    engine = create_engine("sqlite://")
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE decider_inputs(id INTEGER, config_hash TEXT, run_id TEXT, decided_at TIMESTAMP, context_json TEXT, call_kind TEXT)"))
        conn.execute(text(
            "CREATE TABLE decider_memory(id INTEGER, config_hash TEXT, kind TEXT, ticker TEXT, content TEXT, updated_at TIMESTAMP)"))
        conn.execute(text("CREATE TABLE summaries(id INTEGER, config_hash TEXT, run_id TEXT, timestamp TIMESTAMP, data TEXT)"))
        for config in ("cfg", "other"):
            conn.execute(text("""INSERT INTO decider_inputs VALUES(1,:h,'run','2026-11-15 10:00:00',:ctx,'decide')"""),
                         {"h": config, "ctx": json.dumps({"regime": "MIXED", "holdings": ["ABC"], "account_value": "PRIVATE"})})
            for index, content in enumerate(["First lesson", "Second lesson"], start=1):
                conn.execute(text("INSERT INTO decider_memory VALUES(:i,:h,'lesson',NULL,:body,'2026-11-01')"),
                             {"i": index, "h": config, "body": content})
        for index, (when, headline) in enumerate([("09:59:00", "Public headline"), ("10:01:00", "A later outcome")], start=1):
            conn.execute(text("INSERT INTO summaries VALUES(:i,'cfg','run',:at,:s)"),
                         {"i": index, "at": "2026-11-15 " + when, "s": json.dumps({"summary": {"headlines": [headline]}})})
        nodes = []
        for i, title, choice in ((1, "First lesson", "exclude"), (2, "Second lesson", "include"), (3, "Unknown source", "exclude")):
            body = "- [lesson] " + title
            nodes.append({"node_id": f"DA.ltm.{i}", "kind": "ltm", "title": title, "chars": len(body)+1,
                          "text_sha256": hashlib.sha256(body.encode()).hexdigest(), "decisions_choice": choice,
                          "decisions_p": .1 if choice == "exclude" else .9, "served_in_prompt": choice == "include"})
        for index, cfg, source in [(1, "cfg", "live"), (2, "other", "live"), (3, "cfg", "replay")]:
            conn.execute(text("""INSERT INTO policy_router_comparisons
                    (id,config_hash,run_id,prompt_version,decided_at,request_hash,source_input_id,source_kind,
                     status,provider,model,nodes_json,comparison_json,pinned_json)
                VALUES(:i,:h,'run',62,'2026-11-15 10:00:03','hash',1,:s,'ok','openai_decisions','router',:n,:c,'[]')"""),
                         {"i": index, "h": cfg, "s": source, "n": json.dumps(nodes), "c": json.dumps({"requested_mode": "active"})})
    app = Flask(__name__)
    register_policy_graph_routes(app, engine=engine, get_config_hash=lambda: "cfg", repo_root=tmp_path,
                                 is_margin_account=False)
    return engine, app.test_client()


URL = "/api/policy-graph/router-usefulness"


def save(client, item, judgment, **overrides):
    keys = ("comparison_id", "node_id", "revision", "evidence_hash")
    return client.post(URL, json={**{k: item[k] for k in keys}, "config_hash": "cfg", "judgment": judgment, **overrides})


def test_blinded_review_records_judgments_and_measures_only_reviewed_needed(tmp_path):
    engine, client = dashboard(tmp_path)
    first = client.get(URL)
    assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
    assert not inspect(engine).has_table(TABLE)
    data = first.get_json()
    assert data["queue_size"] == 2
    assert data["summary"]["scored"] == 3 and data["summary"]["unavailable"] == 1
    assert data["summary"]["reviewed_recall"] is None
    assert data["item"]["headlines"] == ["Public headline"]
    for term in ("decisions_p", "decisions_choice", "served_in_prompt", "A later outcome", "PRIVATE"):
        assert term not in first.get_data(as_text=True)
    for i in range(2):
        item = client.get(URL).get_json()["item"]
        assert set(item).isdisjoint({"choice", "served", "active"})
        assert save(client, item, "needed").status_code == 200
        assert save(client, item, "irrelevant").status_code == 409
    report = client.get(URL).get_json()
    assert report["item"] is None
    assert report["summary"]["reviewed_recall"] == .5
    assert report["summary"]["active_omitted"] == report["summary"]["proposed_misses"] == 1
    assert report["summary"]["unjudged"] == 1
    reviewed = client.get(URL+"?queue=reviewed").get_json()["item"]
    assert save(client, reviewed, "clear").status_code == 200
    assert client.get(URL).get_json()["summary"]["reviewed"] == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM policy_router_usefulness_reviews")).scalar_one() == 3


def test_only_scored_items_with_matching_evidence_and_scope_can_be_changed(tmp_path):
    engine, client = dashboard(tmp_path)
    item = client.get(URL).get_json()["item"]
    assert save(client, item, "needed", config_hash="other").status_code == 400
    assert save(client, item, "needed", comparison_id=2).status_code == 404
    assert save(client, item, "needed", node_id="DA.ltm.3").status_code == 404
    assert save(client, item, "needed", evidence_hash="stale").status_code == 409
    assert save(client, item, "needed", node_id="DA.code.pinned").status_code == 404
    assert client.get(URL+"?offset=-1").status_code == 400
    assert client.post(URL, json={}, headers={"Origin": "https://other.test"}).status_code == 400
    with engine.begin() as conn:
        conn.execute(text("UPDATE decider_memory SET content='Different recorded text' WHERE config_hash='cfg'"))
    assert save(client, item, "needed").status_code == 404
    assert not inspect(engine).has_table(TABLE)


def test_dialog_load_judge_and_clear_with_mocked_local_api():
    import shutil
    import subprocess
    from pathlib import Path
    import pytest

    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node") or str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
    if not Path(node).exists():
        pytest.skip("Node runtime unavailable")
    script = r"""
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (elements.has(id)) return elements.get(id);
  const e = {value:'unreviewed', dataset:{}, hidden:false, listeners:{}, textContent:'',
    addEventListener(type, fn) {this.listeners[type] = fn;},
    replaceChildren(...children) {this.children = children;},
    querySelector() {return clear;}, querySelectorAll() {return [];},
    showModal() {this.open = true;}, close(){this.open = false;}};
  elements.set(id,e); return e;
}
const clear = element('clear');
global.document = {getElementById:element, createElement:tag=>({...element('li'),tag})};
global.window = {};
const history = [], judgment = {value:null}, tick = () => new Promise(resolve=>setImmediate(resolve));
global.fetch = async (url, options) => {
  history.push(url);
  assert.ok(url.startsWith('/api/policy-graph/router-usefulness'));
  if (options.method === 'POST') {
    const p = JSON.parse(options.body);
    assert.equal(p.config_hash,'cfg'); assert.equal(p.node_id,'DA.ltm.1');
    judgment.value = p.judgment === 'clear' ? null : p.judgment;
    return {ok:true};
  }
  const reviewed = url.includes('queue=reviewed');
  const item = reviewed === Boolean(judgment.value) ? {comparison_id:1, node_id:'DA.ltm.1', judgment:judgment.value,
      evidence_hash:'h', revision:reviewed?1:0, as_of:'2026-11-15',version:62,
      context:{regime:'MIXED',holdings:['ABC']},headlines:['A saved headline'],body:'Saved lesson',basis:'Verified text hash'} : null;
  return {ok:true,json:async()=>({config_hash:'cfg',item,queue_size:item?1:0,window_cycles:100,summary:{
      reviewed:0,unjudged:1,unavailable:0,cycles:1,reviewed_recall:null,active_omitted:0,active_needed:0}})};
};
require(process.argv[1]);
(async()=>{
  element('prReviewOpen').listeners.click(); await tick();
  assert.equal(element('prReviewDialog').open,true);
  assert.equal(element('prReviewBody').textContent,'Saved lesson');
  assert.equal(clear.hidden,true);
  const clickLabel = label => element('prReviewDialog').listeners.click({target:{closest:()=>({dataset:{reviewLabel:label}})}});
  await clickLabel('needed');
  assert.equal(element('prReviewItem').hidden,true);
  element('prReviewQueue').value='reviewed'; element('prReviewQueue').listeners.change(); await tick();
  assert.equal(clear.hidden,false);
  await clickLabel('clear'); assert.equal(judgment.value,null);
  assert.equal(history.length,6);
})().catch(e=>{console.error(e); process.exitCode=1;});
"""
    subprocess.run([node, "-e", script, str(root/"static/js/router-usefulness.js")], check=True)


def test_frozen_summary_references_span_runs_and_stale_reviews_leave_the_denominator(tmp_path):
    engine, client = dashboard(tmp_path)
    ref = {"source_run_id":"previous","source_agent":"Agent_CNBC","summary_id":"5"}
    manifest = {"decision_run_id":"run","config_hash":"cfg","images":[ref,{**ref,"summary_id":"6"},
                {**ref,"summary_id":"7"},{**ref,"summary_id":"8"}]}
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE summaries ADD COLUMN agent TEXT"))
        conn.execute(text("UPDATE policy_router_comparisons SET comparison_json=:j WHERE id=1"),
                     {"j":json.dumps({"image_manifest":manifest,"requested_mode":"active"})})
        for i, agent, run, at, head in [(5,"Agent_CNBC","previous","09:50:00","Matched predecision headline"),
                                        (6,"Agent_CNBC","previous","10:01:00","After decision"),
                                        (7,"WrongAgent","previous","09:40:00","Wrong source"),
                                        (8,"Agent_CNBC","wrong","09:40:00","Wrong run")]:
            conn.execute(text("INSERT INTO summaries VALUES(:i,'cfg',:r,:at,:s,:a)"),
                         {"i":i,"r":run,"a":agent,"at":"2026-11-15 "+at,"s":json.dumps({"summary":{"headlines":[head]}})})
    item = client.get(URL).get_json()["item"]
    assert item["headlines"] == ["Matched predecision headline"]
    assert "frozen image manifest" in item["headline_basis"]
    assert save(client,item,"needed").status_code == 200
    with engine.begin() as conn:
        conn.execute(text("UPDATE summaries SET data=:j WHERE id=5"),
                     {"j":json.dumps({"summary":{"headlines":["Corrected headline"]}})})
    report = client.get(URL).get_json()
    assert report["summary"]["reviewed"] == 0 and report["summary"]["reviewed_recall"] is None
    assert save(client,item,"irrelevant").status_code == 409


def test_old_nodes_without_a_title_or_fingerprint_remain_unavailable(tmp_path):
    engine, client = dashboard(tmp_path)
    with engine.begin() as conn:
        nodes = json.loads(conn.execute(text("SELECT nodes_json FROM policy_router_comparisons WHERE id=1")).scalar_one())
        del nodes[0]["text_sha256"], nodes[0]["title"]
        conn.execute(text("UPDATE policy_router_comparisons SET nodes_json=:j WHERE id=1"), {"j":json.dumps(nodes)})
    result = client.get(URL)
    assert result.status_code == 200 and result.get_json()["summary"]["unavailable"] == 2
