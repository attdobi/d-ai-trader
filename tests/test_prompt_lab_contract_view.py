"""Exercise runtime-usage badges and cross-agent editing without a browser or API."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node") or str(
    Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)


@pytest.mark.skipif(not Path(NODE).exists(), reason="Node.js is unavailable")
def test_prompt_lab_usage_and_agent_version_isolation():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
  const classes = new Set();
  return {
    value: '', textContent: '', hidden: false, disabled: false, dataset: {}, style: {}, handlers: {},
    classList: {add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)),
      contains: x => classes.has(x), toggle: (x, on) => {if (on) classes.add(x); else classes.delete(x);}},
    addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); },
    async fire(type) {for (const handler of this.handlers[type] || []) await handler({target: this});}
  };
}
const ids = ['promptLabAgentType', 'generatePromptBtn', 'applyPromptBtn', 'promptLabResults', 'generatedReasoning',
  'generatedSystemPrompt', 'generatedUserPrompt', 'promptDescription', 'generatedStrategyDirectives', 'generatedSoul',
  'generatedMemory', 'loadActiveBtn', 'promptRuntimeNote', 'promptRuntimeLink', 'promptLabError', 'promptLabSuccess', 'promptLabMessage'];
const elements = Object.fromEntries(ids.map(id => [id, element()]));
const fields = ['system_prompt', 'user_prompt_template', 'strategy_directives', 'soul', 'memory'];
const badges = fields.map(field => Object.assign(element(), {dataset: {contractField: field}}));
const notes = fields.map(field => Object.assign(element(), {dataset: {contractNote: field}}));
elements.promptLabAgentType.value = 'SummarizerAgent';
const context = {console, document: {addEventListener() {}, getElementById: id => elements[id] || null,
  querySelectorAll: selector => selector === '[data-contract-field]' ? badges : selector === '[data-contract-note]' ? notes : []}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const pending = [];
context.apiJSON = (url, options) => {
  if (url === '/api/prompt-evolution/history') return Promise.resolve({});
  return new Promise((resolve, reject) => pending.push({url, options, resolve, reject}));
};
const settle = () => new Promise(resolve => setImmediate(resolve));
function request(fragment) {
  const index = pending.findIndex(item => item.url.includes(fragment));
  assert.ok(index >= 0, 'missing request: ' + fragment);
  return pending.splice(index, 1)[0];
}
function contract(agent, usedFields, url = '/api/policy-graph/compiled?agent=' + agent) {
  return {agent, runtime_note: agent + ' runtime contract', compiled_runtime_url: url,
    fields: Object.fromEntries(fields.map(field => [field, {used: usedFields.includes(field), note: agent + ': ' + field}]))};
}
async function select(agent) {
  elements.promptLabAgentType.value = agent;
  await elements.promptLabAgentType.fire('change');
}
(async () => {
  context.setupPromptLab();
  request('prompt-contracts').resolve(contract('SummarizerAgent', fields));
  await settle();
  assert.ok(badges.every(badge => badge.textContent === 'Used at runtime'));
  assert.equal(elements.promptRuntimeLink.hidden, false);

  await select('FeedbackAgent');
  assert.ok(notes.every(note => note.textContent === ''), 'old field notes must clear while loading');
  request('prompt-contracts').resolve(contract('FeedbackAgent', ['soul'], 'javascript:alert(1)'));
  await settle();
  assert.equal(badges.find(b => b.dataset.contractField === 'soul').textContent, 'Used at runtime');
  assert.ok(badges.filter(b => b.dataset.contractField !== 'soul').every(b => b.textContent === 'Reference only'));
  assert.equal(elements.promptRuntimeLink.hidden, true, 'compiled links must stay inside the local API');

  await select('DeciderAgent');
  request('prompt-contracts').resolve(contract('DeciderAgent', fields));
  const oldLoad = elements.loadActiveBtn.fire('click');
  const oldRequest = request('/DeciderAgent/active');
  await select('CompanyExtractionAgent');
  request('prompt-contracts').resolve(contract('CompanyExtractionAgent', fields));
  oldRequest.resolve({version: 59, system_prompt: 'STALE DECIDER', user_prompt_template: 'STALE'});
  await oldLoad;
  assert.notEqual(elements.generatedSystemPrompt.value, 'STALE DECIDER');
  assert.ok(elements.promptLabResults.classList.contains('pe-hidden'));
  assert.equal(elements.generatePromptBtn.disabled, true);
  await elements.generatePromptBtn.fire('click');
  assert.ok(!pending.some(item => item.url.includes('/generate')), 'Company must not run generic generation');

  const load = elements.loadActiveBtn.fire('click');
  request('/CompanyExtractionAgent/active').resolve({version: 0, system_prompt: 'COMPANY', user_prompt_template: 'INPUT'});
  await load;
  elements.promptDescription.value = 'Clarify extraction';
  const apply = elements.applyPromptBtn.fire('click');
  const applyRequest = request('/apply');
  const payload = JSON.parse(applyRequest.options.body);
  assert.equal(payload.agent_type, 'CompanyExtractionAgent');
  assert.equal(payload.base_version, 0, 'version zero is a valid concurrency guard');
  applyRequest.resolve({success: true, version: 1});
  await apply;

  await select('FeedbackAgent');
  request('prompt-contracts').resolve(contract('FeedbackAgent', ['soul']));
  await elements.applyPromptBtn.fire('click');
  assert.ok(!pending.some(item => item.url.includes('/apply')), 'cannot apply fields loaded for a different agent');
  assert.ok(elements.promptLabError.textContent.includes('Load this agent'));
  await settle();
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "static/js/prompt-evolution.js")],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(not Path(NODE).exists(), reason="Node.js is unavailable")
def test_prompt_lab_restores_cached_no_change_and_focuses_real_draft():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attrs = {};
    this.handlers = {};
    this.textContent = '';
    this.className = '';
    this.classList = {
      add: name => this.classList.toggle(name, true),
      toggle: (name, enabled) => {
        const classes = new Set(this.className.split(' '));
        if (enabled) classes.add(name); else classes.delete(name);
        this.className = [...classes].join(' ');
      }
    };
  }
  set innerHTML(value) {
    this.markup = value;
    this.children = value.includes('<input') ? [new Element()] : [];
  }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  appendChild(child) { this.children.push(child); }
  querySelectorAll(selector) { return this.children.filter(el => el.className.split(' ').includes(selector.slice(1))); }
  querySelector(selector) { return selector === 'input' ? this.children[0] : null; }
  focus() { this.focused = true; }
  content() { return `${this.markup || ''} ${this.textContent} ${this.children.map(child => child.content()).join(' ')}`; }
}
const ids = ['batchGenerateBtn', 'batchStatus', 'batchResults', 'batchTabs', 'batchPanels'];
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
const byId = id => elements[id] || elements.batchTabs.children.find(el => el.id === id) || null;
const cache = {
  stored_at: Date.now(),
  candidates: [
    {agent_type: 'SummarizerAgent', current_version: 33, diffs: {system_prompt_diff: []},
     critic: {verdict: 'reject', confidence: 0.9, auto: true}},
    {agent_type: 'DeciderAgent', current_version: 62, no_change: true, diffs: {}},
    {agent_type: 'FeedbackAgent', current_version: 17,
     diffs: {memory_diff: ['--- old', '+++ new', '@@ -1 +1 @@', '-Original', '+Clarification'], soul_diff: []},
     change_summary: {wording_only: true}, critic: {verdict: 'reject', confidence: 0.9, auto: true}}
  ]
};
const context = {console, document: {addEventListener() {}, getElementById: byId,
  createElement: () => new Element(), createTextNode: value => Object.assign(new Element(), {textContent: value})},
  localStorage: {getItem: key => key === 'pe.lastBatchResult' ? JSON.stringify(cache) : null, removeItem() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.setupBatchPromptLab();
const [summarizer, decider, feedback] = elements.batchPanels.children;
assert.match(summarizer.content(), /No change proposed/);
assert.match(decider.content(), /Active version v62/);
assert.doesNotMatch(summarizer.content(), /Approve|confidence|v34/);
assert.doesNotMatch(decider.content(), /Approve|confidence|v63/);
assert.match(feedback.content(), /Wording-only draft/);
assert.doesNotMatch(feedback.content(), /No changes from active version|90%|Critic recommends rejecting/);
assert.equal(feedback.querySelectorAll('.pe-diff-section').length, 1);
assert.match(elements.batchStatus.textContent, /1 draft to review · 2 with no change proposed/);
assert.equal(byId('batch-tab-FeedbackAgent').attrs['aria-selected'], 'true');
byId('batch-tab-FeedbackAgent').handlers.keydown({key: 'ArrowRight', preventDefault() {}});
assert.equal(byId('batch-tab-SummarizerAgent').attrs['aria-selected'], 'true');
assert.equal(byId('batch-tab-SummarizerAgent').focused, true);
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "static/js/prompt-evolution.js")],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
