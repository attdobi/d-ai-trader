"""GPT-6 selections reach the reasoning/vision path without DB or network calls."""
from __future__ import annotations

import base64
import subprocess
import types
from pathlib import Path

import pytest

from tests.test_gpt56_models import _cfg


MODELS = ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")


@pytest.mark.parametrize("model", MODELS)
def test_gpt6_full_ids_and_reasoning_suffixes(monkeypatch, model):
    cfg = _cfg(monkeypatch, env={"DAI_CRITIC_REASONING_LEVEL": None})
    cfg.set_gpt_model(model + "-max")
    assert cfg.get_gpt_model() == model
    assert cfg.GLOBAL_REASONING_LEVEL == "max"
    assert cfg.get_reasoning_params("DeciderAgent", model) == {"reasoning_effort": "max"}
    assert cfg.get_reasoning_token_cap("DeciderAgent", model, 1500) == 32000
    assert cfg.get_model_token_params(model, 12000) == {"max_completion_tokens": 12000}
    assert cfg.get_model_temperature_params(model, 0.2) == {}


def test_gpt6_agent_overrides_preserve_reasoning_profiles(monkeypatch):
    cfg = _cfg(monkeypatch, env={
        "DAI_MODEL_DECIDER": "gpt-6.1-sol", "DAI_MODEL_FEEDBACK": "gpt-6.1-sol",
        "DAI_MODEL_CRITIC": "gpt-6.1-sol", "DAI_MODEL_EVOLUTION": "gpt-6.1-sol",
        "DAI_MODEL_SUMMARIZER": "gpt-6-luna", "DAI_MODEL_COMPANY": "gpt-6-luna",
        "DAI_CRITIC_REASONING_LEVEL": None,
    })
    for agent in ("DeciderAgent", "FeedbackAgent", "CriticAgent", "PromptEvolutionAgent"):
        assert cfg.get_agent_model(agent) == "gpt-6.1-sol"
        assert cfg.get_reasoning_params(agent, cfg.get_agent_model(agent)) == {"reasoning_effort": "high"}
    assert cfg.get_agent_model("SummarizerAgent") == "gpt-6-luna"
    assert cfg.get_agent_model("CompanyExtractionAgent") == "gpt-6-luna"


def _client(outcomes, calls):
    def create(**params):
        calls.append(params)
        content, finish = outcomes.pop(0)
        return types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(
            finish_reason=finish, message=types.SimpleNamespace(content=content))])
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("agent,level,cap", [("DeciderAgent", "high", 12000), ("SummarizerAgent", "low", 4000)])
def test_gpt6_call_keeps_images_reasoning_budget_and_replay(monkeypatch, tmp_path, model, agent, level, cap):
    cfg = _cfg(monkeypatch, env={
        "DAI_GPT_MODEL": model, "DAI_DECIDER_REASONING_LEVEL": "high",
        "DAI_SUMMARIZER_REASONING_LEVEL": "low",
    })
    image_bytes = b"local-test-image"
    picture = tmp_path / "screen.png"
    picture.write_bytes(image_bytes)
    calls = []
    pm = cfg.PromptManager(_client([('  {"decisions": []}  ', "stop")], calls), session=None)
    assert pm.ask_openai("NEWS", "SYSTEM JSON", agent_name=agent, image_paths=[picture]) == {"decisions": []}
    assert len(calls) == 1
    sent = calls[0]
    assert sent["model"] == model and sent["reasoning_effort"] == level
    assert sent["max_completion_tokens"] == cap
    assert "max_tokens" not in sent and "temperature" not in sent
    user_content = sent["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "NEWS"}
    assert user_content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    if agent == "SummarizerAgent":
        assert sent["response_format"] == {"type": "json_object"}
    else:
        assert "response_format" not in sent
    last = pm.last_reply()
    assert last["model"] == model and last["reasoning_effort"] == level
    assert last["system_prompt"] == sent["messages"][0]["content"]
    assert last["content"] == '  {"decisions": []}  '


@pytest.mark.parametrize("model", ("gpt-6.1-sol", "gpt-6-luna"))
def test_gpt6_rejects_truncated_decisions_even_if_json_parses(monkeypatch, model):
    cfg = _cfg(monkeypatch, env={"DAI_GPT_MODEL": model})
    calls = []
    pm = cfg.PromptManager(_client([('{"decisions": [{"action": "buy"}]}', "length")], calls), session=None)
    result = pm.ask_openai("NEWS", "JSON", agent_name="DeciderAgent", max_retries=1)
    assert "error" in result and "exhausted reasoning tokens" in result["error"]
    assert "decisions" not in result


def test_gpt6_empty_decisions_use_existing_fallback(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_GPT_MODEL": "gpt-6.1-sol", "DAI_DECIDER_FALLBACK_MODEL": "gpt-4.1"})
    calls = []
    pm = cfg.PromptManager(_client([("[]", "stop"), ('[{"action": "hold"}]', "stop")], calls), session=None)
    assert pm.ask_openai("NEWS", "JSON", agent_name="DeciderAgent") == [{"action": "hold"}]
    assert [c["model"] for c in calls] == ["gpt-6.1-sol", "gpt-4.1"]
    assert pm.last_reply()["model"] == "gpt-4.1"
    assert pm.last_reply()["reasoning_effort"] is None


@pytest.mark.parametrize("model,expected", [
    ("gpt-6.1-sol", 12.0), ("gpt-6.1-terra", 6.0), ("gpt-6-astra", 60.0),
    ("gpt-6-sol", 12.0), ("gpt-6-luna", 0.6), ("gpt-5.6-sol", 24.0),
])
def test_gpt6_cost_estimates_include_reasoning_in_output(monkeypatch, model, expected):
    cfg = _cfg(monkeypatch)
    assert cfg.compute_api_cost(model, 1_000_000, 1_000_000) == pytest.approx(expected)


def test_launcher_advertises_full_ids_without_changing_default():
    launcher = Path(__file__).resolve().parents[1] / "start_d_ai_trader.sh"
    help_text = subprocess.run(["bash", str(launcher), "--help"], check=True, capture_output=True,
                               text=True, timeout=20).stdout
    assert all(model in help_text for model in MODELS)
    assert "Global AI model (default: gpt-5.6-terra)" in help_text
    assert "aliases still select GPT-5.6" in help_text
