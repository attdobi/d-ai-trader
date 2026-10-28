"""Read hosted-router usage at its own tariff, separate from Chat repricing.

The Decisions provider writes one comparison row per request attempt. Its
recorded estimate already accounts for cached input, cache writes and free
output, so applying the Chat model's token prices here would misstate spend.
No configuration imports, schema creation or database writes occur here.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

DECISIONS_AGENT = "PolicyRouterDecisions"


def decisions_daily_usage(engine, config_hash: str, start_date) -> dict:
    """Bounded daily totals; missing optional tables are a normal fresh install.

    Preflight failures with no request attempt are not API calls. A failed or
    refused request with usage still contributes its recorded cost. Attempts
    without usage are counted explicitly as unknown, never as confirmed free.
    """
    if not inspect(engine).has_table("policy_router_comparisons"):
        return {"available": False, "daily": []}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DATE(decided_at) AS day,
                   COUNT(*) AS calls,
                   COALESCE(SUM(input_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                   COALESCE(SUM(output_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cost_usd), 0) AS known_cost,
                   SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unknown_cost_calls,
                   SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL
                            THEN 1 ELSE 0 END) AS unknown_token_calls
            FROM policy_router_comparisons
            WHERE config_hash = :h AND decided_at >= :start
                  AND provider = 'openai_decisions' AND request_attempted = TRUE
            GROUP BY DATE(decided_at)
            ORDER BY DATE(decided_at)
        """), {"h": config_hash, "start": start_date}).mappings().all()
    daily = []
    for row in rows:
        item = dict(row)
        day = item["day"]
        item["day"] = day.isoformat() if hasattr(day, "isoformat") else str(day)
        for key in ("calls", "prompt_tokens", "cached_input_tokens", "cache_write_tokens",
                    "completion_tokens", "unknown_cost_calls", "unknown_token_calls"):
            item[key] = int(item[key] or 0)
        item["known_cost"] = float(item["known_cost"] or 0)
        item["cost"] = None if item["unknown_cost_calls"] else item["known_cost"]
        daily.append(item)
    return {"available": True, "daily": daily}
