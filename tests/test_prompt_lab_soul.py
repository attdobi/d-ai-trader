"""Offline Prompt Lab generation with the current approved Soul headings."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_dashboard_imports import (  # noqa: F401
    dashboard_server_module, isolated_cash_flows, isolated_policy_graph,
)


@pytest.mark.parametrize('agent,directory', [
    ('SummarizerAgent', 'summarizer'),
    ('DeciderAgent', 'decider'),
    ('FeedbackAgent', 'feedback'),
])
def test_prompt_lab_generation_keeps_approved_soul_sections(dashboard_server_module, monkeypatch, agent, directory):
    dashboard, _ = dashboard_server_module
    source = (Path(dashboard.__file__).parent / 'agents' / directory / 'SOUL.default.md').read_text()
    current = SimpleNamespace(
        version=61, description='Approved version', soul=source, memory='Memory',
        system_prompt='Use the holdings source of truth. Never invent holdings.',
        user_prompt_template='Return the "cited" field.', strategy_directives='',
    )
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
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'system_prompt': current.system_prompt,
            'user_prompt_template': current.user_prompt_template,
            'soul_edits': {key: original + '\n\nAn agent-specific clarification.', '1': '## Mission\nReplace it.'},
        })))])

    def openai_client(*, timeout, max_retries):
        assert timeout == dashboard._PROMPT_LAB_MODEL_TIMEOUT_SEC
        assert max_retries == 0
        return Client(completion)

    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=openai_client))
    candidate = dashboard._generate_candidate_for_agent(agent, 'test-config')
    locked = {'mission', 'principles'}
    expected = [(name, body) for name, body in dashboard._soul_draft_sections(source) if name in locked]
    actual = [(name, body) for name, body in dashboard._soul_draft_sections(candidate['soul']) if name in locked]
    assert actual == expected
    assert 'An agent-specific clarification.' in candidate['soul']
    assert 'Replace it.' not in candidate['soul']


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
