"""Offline Prompt Lab generation with the current approved Soul headings."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_dashboard_imports import (  # noqa: F401
    dashboard_server_module, isolated_cash_flows, isolated_policy_graph,
)


@pytest.mark.parametrize('agent,directory,citation_layout', [
    ('SummarizerAgent', 'summarizer', None),
    ('DeciderAgent', 'decider', 'system'),
    ('DeciderAgent', 'decider', 'legacy-user'),
    ('DeciderAgent', 'decider', 'removed'),
    ('FeedbackAgent', 'feedback', None),
])
def test_prompt_lab_generation_preserves_contracts(dashboard_server_module, monkeypatch, agent, directory, citation_layout):
    dashboard, _ = dashboard_server_module
    root = Path(dashboard.__file__).parent
    source = (root / 'agents' / directory / 'SOUL.default.md').read_text()
    current = SimpleNamespace(
        version=61, description='Approved version', soul=source, memory='Memory',
        system_prompt='Use the holdings source of truth. Never invent holdings.',
        user_prompt_template='Return decisions as JSON.', strategy_directives='',
    )
    if citation_layout in {'system', 'removed'}:
        audited = json.loads((root / 'policy_graph/audited_agent_prompts.json').read_text())['agents'][agent]['fields']
        current.system_prompt = audited['system_prompt']
        current.user_prompt_template = audited['user_prompt_template']
        assert '"cited":' in current.system_prompt and '"cited"' not in current.user_prompt_template
    elif citation_layout == 'legacy-user':
        current.user_prompt_template = 'Return {"decisions":[{"cited": ["guideline id"]}]}'
    monkeypatch.setattr(dashboard, 'engine', SimpleNamespace(connect=lambda: Connection(current)))
    for name in ('_load_prompt_evolution_context', '_fetch_prompt_review_history', '_fetch_trade_evidence', '_safe_diagnostics'):
        monkeypatch.setattr(dashboard, name, lambda *args, **kwargs: {})
    monkeypatch.setattr(dashboard._prompt_lab_usage, '_record_api_usage', lambda *args: None, raising=False)

    def completion(**kwargs):
        sent = json.loads(kwargs['messages'][-1]['content'].split('\n\n', 1)[1])['current_prompt']
        editable = sent['editable_soul_sections']
        assert editable
        assert all('## Mission' not in body and '## Shared Principles' not in body for body in editable.values())
        key, original = next(iter(editable.items()))
        system = current.system_prompt
        if citation_layout == 'removed':
            system = system.replace('"cited":[', '"removed":[') + '\nRemember "cited".'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'system_prompt': system,
            'user_prompt_template': current.user_prompt_template,
            'soul_edits': {key: original + '\n\nAn agent-specific clarification.', '1': '## Mission\nReplace it.'},
        })))])

    def openai_client(*, timeout, max_retries):
        assert timeout == dashboard._PROMPT_LAB_MODEL_TIMEOUT_SEC
        assert max_retries == 0
        return Client(completion)

    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=openai_client))
    if citation_layout == 'removed':
        with pytest.raises(ValueError, match='dropped the required "cited" guideline-ID array'):
            dashboard._generate_candidate_for_agent(agent, 'test-config')
        return
    candidate = dashboard._generate_candidate_for_agent(agent, 'test-config')
    locked = {'mission', 'principles'}
    expected = [(name, body) for name, body in dashboard._soul_draft_sections(source) if name in locked]
    actual = [(name, body) for name, body in dashboard._soul_draft_sections(candidate['soul']) if name in locked]
    assert actual == expected
    assert 'An agent-specific clarification.' in candidate['soul']
    assert 'Replace it.' not in candidate['soul']


@pytest.mark.parametrize('approve_system', [False, True])
def test_apply_validates_citation_array_after_merging_approved_sections(dashboard_server_module, monkeypatch, approve_system):
    dashboard, _ = dashboard_server_module
    current = SimpleNamespace(
        system_prompt='Return {"decisions":[{"cited":["guideline id"]}]}',
        user_prompt_template='Analyze {summaries}.', strategy_directives='Original rules',
        soul='Original soul', memory='Original memory',
    )
    payload = {
        'agent_type': 'DeciderAgent', 'description': 'Test partial approval',
        'system_prompt': 'Return {"decisions":[]}.',
        'user_prompt_template': 'Return {"decisions":[{"cited":["guideline id"]}]}',
        'strategy_directives': 'Revised rules',
        'approved_sections': ['system_prompt' if approve_system else 'strategy_directives'],
    }
    writes = []

    class ApplyConnection(Connection):
        def execute(self, statement, params):
            if 'INSERT INTO prompt_versions' in statement:
                writes.append(params)
            return SimpleNamespace(fetchone=lambda: SimpleNamespace(max_version=61))

    monkeypatch.setattr(dashboard.request, 'get_json', lambda silent: payload, raising=False)
    monkeypatch.setattr(dashboard, 'engine', SimpleNamespace(connect=lambda: Connection(current), begin=lambda: ApplyConnection(current)))
    monkeypatch.setattr(dashboard, 'set_active_prompt_version', lambda *args, **kwargs: {})
    monkeypatch.setattr(dashboard, 'refresh_latest_policy_graph', lambda *args, **kwargs: None)
    response = dashboard.apply_prompt_evolution_candidate()

    if approve_system:
        assert response[1] == 400
        assert 'required "cited" guideline-ID' in response[0]['args'][0]['error']
        assert not writes
    else:
        assert response['args'][0]['success'] is True
        assert writes[0]['system_prompt'] == current.system_prompt
        assert writes[0]['user_prompt_template'] == current.user_prompt_template
        assert writes[0]['strategy_directives'] == payload['strategy_directives']


class Connection:
    def __init__(self, prompt):
        self.prompt = prompt

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, statement, params):
        return SimpleNamespace(fetchone=lambda: self.prompt, fetchall=lambda: [])


class Client:
    def __init__(self, completion):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=completion))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None
