"""PromptManager.last_reply describes only the attempt that produced ask_openai's return value: a retried
attempt's discarded text is never left behind for decider_inputs to log as the reply the trader acted on."""
from __future__ import annotations

import types

from tests.test_config_model_overrides import _import_config

ENV = {"DAI_GPT_MODEL": "gpt-5.4", "DAI_MODEL_DECIDER": None, "DAI_DECIDER_REASONING_LEVEL": "high",
       "DAI_REASONING_LEVEL": None, "DAI_DISABLE_REASONING_PARAM": None}


def _pm(monkeypatch, outcomes):
    """A PromptManager whose client plays `outcomes` in order: a str is a completion, an Exception is raised."""
    cfg = _import_config(monkeypatch, env=ENV)
    monkeypatch.setattr(cfg.time, "sleep", lambda *_: None)
    calls = []

    class _Completions:
        def create(self, **params):
            calls.append(params)
            out = outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            msg = types.SimpleNamespace(content=out)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason="stop", message=msg)], usage=None)

    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()))
    return cfg.PromptManager(client=client, session=None), calls


def test_api_error_after_a_retried_reply_leaves_no_stale_last_reply(monkeypatch):
    pm, calls = _pm(monkeypatch, ["not json at all", RuntimeError("timeout"), RuntimeError("timeout")])
    out = pm.ask_openai("USER", "SYS", agent_name="DeciderAgent")
    assert len(calls) == 3 and out["headlines"] == ["API error occurred"]
    assert pm.last_reply() is None             # attempt 1's discarded text is not "the reply"


def test_success_after_a_failed_attempt_records_the_final_reply(monkeypatch):
    pm, _calls = _pm(monkeypatch, [RuntimeError("timeout"), '{"decisions": []}'])
    assert pm.ask_openai("USER", "SYS", agent_name="DeciderAgent") == {"decisions": []}
    assert pm.last_reply()["content"] == '{"decisions": []}'


def test_retry_after_a_bad_reply_records_the_reply_that_was_used(monkeypatch):
    pm, _calls = _pm(monkeypatch, ["not json at all", '{"decisions": [1]}'])
    assert pm.ask_openai("USER", "SYS", agent_name="DeciderAgent") == {"decisions": [1]}
    assert pm.last_reply()["content"] == '{"decisions": [1]}'
