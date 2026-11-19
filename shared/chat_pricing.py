"""Standard Chat Completions pricing, including cache usage when captured."""
import math
import re


def completion_usage(usage):
    """Copy metered Chat counters without manufacturing prices from missing data."""
    def field(value, key):
        return value.get(key) if isinstance(value, dict) else getattr(value, key, None)

    result = {}
    def add(raw, key, target=None):
        count = field(raw, key)
        if type(count) is int and count >= 0:
            result[target or key] = count

    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        add(usage, key)
    details = field(usage, "prompt_tokens_details")
    add(details, "cached_tokens", "cached_input_tokens")
    add(details, "cache_write_tokens")
    if "cache_write_tokens" in result:
        result["cache_retention"] = field(details, "cache_retention") or "30m"
    add(field(usage, "completion_tokens_details"), "reasoning_tokens")
    return result


def usage_cost(model, usage, pricing):
    """Known standard tariff only. Missing cache tariff is unknown, never free."""
    rates = (pricing or {}).get(model)
    if rates is None and isinstance(model, str):
        rates = (pricing or {}).get(re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model))

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
    retention = usage.get("cache_retention") or "30m"
    write_key = {"30m": "cache_write", "12h": "cache_write_12h"}.get(retention)
    cached_rate, write_rate = rates.get("cached_input"), rates.get(write_key)

    if cached and (not isinstance(cached_rate, (int, float)) or isinstance(cached_rate, bool) or not math.isfinite(cached_rate) or cached_rate < 0):
        return None
    if writes and (not isinstance(write_rate, (int, float)) or isinstance(write_rate, bool) or not math.isfinite(write_rate) or write_rate < 0):
        return None
    uncached = values["prompt_tokens"] - cached - writes
    input_cost = uncached * incoming + cached * (cached_rate or 0) + writes * (write_rate or 0)
    output_cost = values["completion_tokens"] * output
    if rates.get("long_input_threshold") and values["prompt_tokens"] > rates["long_input_threshold"]:
        input_cost *= 2
        output_cost *= 1.5
    return (input_cost + output_cost) / 1_000_000
