"""Lazy bounded OpenAI adapter for explicit policy replay jobs. No trader import.

The existing application config loads credentials; this module never reads or
prints them. Construction is inert; the first explicit runner invocation creates
the SDK client with no retries. API usage is logged as PolicyReplayAgent.
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.chat_pricing import usage_cost

from .learning_replay import openai_runner

AGENT = "PolicyReplayAgent"


def _pricing():
    try:
        return json.loads((Path(__file__).resolve().parents[1] / "model_pricing.json").read_text())
    except (OSError, ValueError):
        return {}


def _record_usage(engine, config_hash, request, answer):
    if engine is None or not config_hash:
        return
    usage = answer.get("usage") or {}
    try:
        from api_cost_usage import record_chat_usage
        record_chat_usage(engine, config_hash=config_hash,
                          run_id=f"policy-replay-input-{request['source_input_id']}-{request['side']}",
                          agent=AGENT, model=answer.get("model") or request["model"],
                          usage=usage, cost=answer.get("cost_usd"))
    except Exception:
        # Usage writes cannot turn a completed billed request into a retry.
        pass


def make_openai_runner(*, engine=None, config_hash=None, max_completion_tokens=3000, timeout=60.0,
                       client_factory=None, pricing=None):
    """No client/network until invocation. Same request model/effort, no fallback.

    ``client_factory`` is an SDK-compatible test seam. The dashboard passes its
    existing engine/config hash; a standalone caller may omit usage persistence.
    """
    if not 0 < float(timeout) <= 120:
        raise ValueError("replay timeout must be positive and at most 120 seconds")
    if not 128 <= int(max_completion_tokens) <= 12000:
        raise ValueError("replay completion cap must be between 128 and 12000")
    client = None
    def run(request):
        nonlocal client
        if request.get("config_hash") and config_hash and request["config_hash"] != config_hash:
            raise ValueError("replay usage configuration differs from frozen request")
        if client is None:
            if client_factory is None:
                from openai import OpenAI
                factory = OpenAI
            else:
                factory = client_factory
            client = factory(max_retries=0, timeout=float(timeout), base_url="https://api.openai.com/v1")
        answer = openai_runner(client, max_completion_tokens=max_completion_tokens)(request)
        answer["cost_usd"] = usage_cost(answer.get("model"), answer.get("usage") or {}, pricing if pricing is not None else _pricing())
        _record_usage(engine, config_hash, request, answer)
        return answer
    return run


__all__ = ["AGENT", "make_openai_runner", "usage_cost"]
