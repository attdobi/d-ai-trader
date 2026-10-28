"""Lazy bounded OpenAI adapter for explicit policy replay jobs. No trader import.

The existing application config loads credentials; this module never reads or
prints them. Construction is inert; the first explicit runner invocation creates
the SDK client with no retries. API usage is logged as PolicyReplayAgent.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from sqlalchemy import text

from .learning_replay import openai_runner

AGENT = "PolicyReplayAgent"


def _pricing():
    try:
        return json.loads((Path(__file__).resolve().parents[1] / "model_pricing.json").read_text())
    except (OSError, ValueError):
        return {}


def usage_cost(model, usage, pricing):
    """Known standard tariff only. Missing cache tariff is unknown, never free."""
    rates = (pricing or {}).get(model) or {}
    if not isinstance(rates, dict):
        return None
    values = {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens")}
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in values.values()):
        return None
    incoming, output = rates.get("input"), rates.get("output")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in (incoming, output)):
        return None
    cached = usage.get("cached_input_tokens", 0)
    writes = usage.get("cache_write_tokens", 0)
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in (cached, writes)):
        return None
    if cached + writes > values["prompt_tokens"]:
        return None
    cached_rate, write_rate = rates.get("cached_input"), rates.get("cache_write")
    if cached and (not isinstance(cached_rate, (int, float)) or isinstance(cached_rate, bool) or not math.isfinite(cached_rate) or cached_rate < 0):
        return None
    if writes and (not isinstance(write_rate, (int, float)) or isinstance(write_rate, bool) or not math.isfinite(write_rate) or write_rate < 0):
        return None
    return ((values["prompt_tokens"] - cached - writes) * incoming
            + cached * (cached_rate or 0) + writes * (write_rate or 0)
            + values["completion_tokens"] * output) / 1_000_000


def _record_usage(engine, config_hash, request, response, answer):
    if engine is None or not config_hash:
        return
    usage = answer.get("usage") or {}
    if not usage:
        return
    details = getattr(getattr(response, "usage", None), "completion_tokens_details", None)
    reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)
    serial = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS api_usage (
                    id {serial}, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP, config_hash TEXT, run_id TEXT,
                    agent_type TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
                    reasoning_tokens INTEGER, total_tokens INTEGER, cost_usd DOUBLE PRECISION
                )
            """))
            conn.execute(text("""
                INSERT INTO api_usage (config_hash,run_id,agent_type,model,prompt_tokens,completion_tokens,
                    reasoning_tokens,total_tokens,cost_usd)
                VALUES (:h,:r,:a,:m,:p,:c,:reasoning,:total,:cost)
            """), {"h": config_hash, "r": f"policy-replay-input-{request['source_input_id']}-{request['side']}",
                   "a": AGENT, "m": answer.get("model") or request["model"], "p": usage.get("prompt_tokens"),
                   "c": usage.get("completion_tokens"), "reasoning": reasoning,
                   "total": usage.get("total_tokens"), "cost": answer.get("cost_usd")})
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
    latest_response = None
    def remember(_request, response):
        nonlocal latest_response
        latest_response = response
    def run(request):
        nonlocal client, latest_response
        if request.get("config_hash") and config_hash and request["config_hash"] != config_hash:
            raise ValueError("replay usage configuration differs from frozen request")
        if client is None:
            if client_factory is None:
                from openai import OpenAI
                factory = OpenAI
            else:
                factory = client_factory
            client = factory(max_retries=0, timeout=float(timeout), base_url="https://api.openai.com/v1")
        latest_response = None
        answer = openai_runner(client, max_completion_tokens=max_completion_tokens,
                               usage_callback=remember)(request)
        answer["cost_usd"] = usage_cost(answer.get("model"), answer.get("usage") or {}, pricing if pricing is not None else _pricing())
        _record_usage(engine, config_hash, request, latest_response, answer)
        return answer
    return run


__all__ = ["AGENT", "make_openai_runner", "usage_cost"]
