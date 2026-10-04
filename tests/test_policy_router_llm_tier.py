"""policy_router.llm_tier with a fake chat endpoint: P(yes) from logprobs, the constrained-JSON fallback,
auto-detection (model not loaded → skipped), the uncertain band, logit-space combination and the budget."""
from __future__ import annotations

import math
import time

import pytest

from policy_router.llm_tier import LLMTier, combine, p_from_json_answer, p_yes_from_logprobs


def _models(*ids):
    return lambda url, timeout: {"data": [{"id": i} for i in ids]}


def _logprob_answer(p_yes: float):
    return {"choices": [{"message": {"content": "yes"}, "logprobs": {"content": [{
        "token": "yes", "logprob": math.log(p_yes),
        "top_logprobs": [{"token": "yes", "logprob": math.log(p_yes)}, {"token": " No", "logprob": math.log(1 - p_yes)},
                         {"token": "maybe", "logprob": math.log(0.0001)}]}]}}]}


class FakeChat:
    def __init__(self, *, logprobs=True, p=0.9, delay=0.0, fail=None):
        self.logprobs, self.p, self.delay, self.fail = logprobs, p, delay, fail
        self.payloads = []

    def __call__(self, url, payload, timeout):
        assert url.endswith("/chat/completions")
        self.payloads.append(payload)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        if payload.get("logprobs") and self.logprobs:
            return _logprob_answer(self.p)
        if payload.get("logprobs"):
            return {"choices": [{"message": {"content": "yes"}}]}            # server ignores logprobs
        return {"choices": [{"message": {"content": '{"p": %s}' % self.p}}]}


def test_p_yes_from_logprobs_normalizes_over_yes_and_no():
    assert p_yes_from_logprobs(_logprob_answer(0.8)) == pytest.approx(0.8, abs=1e-6)
    assert p_yes_from_logprobs({"choices": [{"message": {"content": "yes"}}]}) is None
    assert p_from_json_answer({"choices": [{"message": {"content": '{"p": 0.25}'}}]}) == 0.25
    assert p_from_json_answer({"choices": [{"message": {"content": 'p: 0.7'}}]}) == 0.7
    assert p_from_json_answer({"choices": [{"message": {"content": '{"p": 4}'}}]}) is None


def test_combine_is_a_logit_average():
    assert combine(0.5, 0.9, 0.5) == pytest.approx(1 / (1 + math.exp(-0.5 * math.log(9))))
    assert combine(0.3, 0.9, 0.0) == pytest.approx(0.3, abs=1e-6)
    assert combine(0.3, 0.9, 1.0) == pytest.approx(0.9, abs=1e-6)


def test_refine_asks_only_the_uncertain_band_with_logprobs():
    chat = FakeChat(p=0.9)
    logs = []
    tier = LLMTier("http://fake/v1", "qwen-local", transport=chat, get_transport=_models("qwen-local"), log=logs.append)
    items = [("a", "text a", 0.5), ("b", "text b", 0.95), ("c", "text c", 0.3), ("d", "text d", 0.05)]
    out, info = tier.refine("context", items)
    assert set(out) == {"a", "c"} and info["answered"] == 2 and info["logprobs"] is True
    assert out["a"] == pytest.approx(combine(0.5, 0.9, 0.5)) and out["a"] > 0.5
    assert all(p["max_tokens"] == 1 and p["logprobs"] for p in chat.payloads)
    assert "Will this guideline be needed" in chat.payloads[0]["messages"][1]["content"]
    assert not logs


def test_refine_falls_back_to_constrained_json_when_logprobs_are_missing():
    chat = FakeChat(logprobs=False, p=0.2)
    tier = LLMTier("http://fake/v1", "m", transport=chat, get_transport=_models("m"), log=lambda *_: None)
    out, info = tier.refine("ctx", [("a", "t", 0.6), ("b", "t", 0.4)])
    assert info["logprobs"] is False and set(out) == {"a", "b"}
    json_calls = [p for p in chat.payloads if "response_format" in p]
    assert json_calls and json_calls[0]["response_format"]["type"] == "json_schema"
    assert len(chat.payloads) == 3                                    # one logprobs probe, then JSON only


def test_refine_skips_without_model_or_when_not_loaded():
    out, info = LLMTier("http://fake/v1", "", transport=FakeChat()).refine("ctx", [("a", "t", 0.5)])
    assert out == {} and info["skipped"] == "no chat model configured"
    logs = []
    tier = LLMTier("http://fake/v1", "big-model", transport=FakeChat(), get_transport=_models("text-embedding-nomic"),
                   log=logs.append)
    out, info = tier.refine("ctx", [("a", "t", 0.5)])
    assert out == {} and "not loaded" in info["skipped"] and len(logs) == 1
    down = LLMTier("http://fake/v1", "m", transport=FakeChat(),
                   get_transport=lambda url, timeout: (_ for _ in ()).throw(ConnectionRefusedError()), log=lambda *_: None)
    assert down.available() is False


def test_refine_stops_on_budget_and_on_errors_without_raising():
    logs = []
    slow = LLMTier("http://fake/v1", "m", transport=FakeChat(delay=0.3), get_transport=_models("m"), budget_s=0.5,
                   per_call_s=0.2, log=logs.append)
    t0 = time.monotonic()
    out, info = slow.refine("ctx", [("a", "t", 0.5), ("b", "t", 0.45), ("c", "t", 0.55)])
    assert time.monotonic() - t0 < 1.5 and out == {} and info["skipped"] and len(logs) == 1
    logs.clear()
    broken = LLMTier("http://fake/v1", "m", transport=FakeChat(fail=RuntimeError("500")), get_transport=_models("m"),
                     log=logs.append)
    out, info = broken.refine("ctx", [("a", "t", 0.5)])
    assert out == {} and "RuntimeError" in info["skipped"] and len(logs) == 1
