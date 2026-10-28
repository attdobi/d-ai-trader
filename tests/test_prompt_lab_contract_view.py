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
