"""Immutable taxonomy review audit, separate from trading policy activation."""
from __future__ import annotations

import json
import math
import re

from sqlalchemy import inspect, text

DDL = """CREATE TABLE IF NOT EXISTS policy_taxonomy_reviews (
 id SERIAL PRIMARY KEY, config_hash VARCHAR(50) NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 taxonomy_version TEXT NOT NULL, source_hash TEXT NOT NULL,
 model TEXT NOT NULL, review_json TEXT NOT NULL, usage_json TEXT NOT NULL,
 cost_usd DOUBLE PRECISION,
 UNIQUE(config_hash,taxonomy_version,source_hash))"""


def save_review(engine, config_hash, review, *, model, usage, cost_usd):
    """Caller must pass the source-validated proposal, never a raw model reply."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", str(config_hash)):
        raise ValueError("Invalid configuration")
    if cost_usd is not None and (not isinstance(cost_usd, (int,float)) or isinstance(cost_usd,bool)
                                or not math.isfinite(cost_usd) or cost_usd < 0):
        raise ValueError("Invalid review cost")
    if review.get("status") != "model_proposed_organization_not_policy":
        raise ValueError("A validated taxonomy proposal is required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(review.get("source_hash"))):
        raise ValueError("A frozen source hash is required")
    usage = {key: int(value) for key,value in usage.items()
             if key in ("prompt_tokens","completion_tokens","reasoning_tokens","total_tokens","cached_input_tokens")
             and isinstance(value,int) and not isinstance(value,bool) and value >= 0}
    with engine.begin() as conn:
        conn.execute(text(DDL if engine.dialect.name == "postgresql" else DDL.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")))
        ident=conn.execute(text("""INSERT INTO policy_taxonomy_reviews
            (config_hash,taxonomy_version,source_hash,model,review_json,usage_json,cost_usd)
            VALUES (:h,:v,:s,:m,:r,:u,:c)
            ON CONFLICT (config_hash,taxonomy_version,source_hash) DO NOTHING RETURNING id"""),
            {"h":config_hash,"v":review["taxonomy_version"],"s":review["source_hash"],"m":model,
             "r":json.dumps(review,ensure_ascii=False,allow_nan=False),"u":json.dumps(usage),"c":cost_usd}).scalar()
        if ident is None:
            ident=conn.execute(text("SELECT id FROM policy_taxonomy_reviews WHERE config_hash=:h AND taxonomy_version=:v AND source_hash=:s"),
                {"h":config_hash,"v":review["taxonomy_version"],"s":review["source_hash"]}).scalar_one()
    return int(ident)


def latest_review(engine, config_hash):
    """Read a scoped bounded audit; viewing the map never calls a model."""
    try:
        if not inspect(engine).has_table("policy_taxonomy_reviews"):
            return None
        with engine.connect() as conn:
            row=conn.execute(text("SELECT * FROM policy_taxonomy_reviews WHERE config_hash=:h ORDER BY id DESC LIMIT 1"),
                             {"h":config_hash}).mappings().first()
        if row is None:
            return None
        result=json.loads(row["review_json"])
        result.update(id=row["id"], model=row["model"], cost_usd=row["cost_usd"], usage=json.loads(row["usage_json"]),
                      created_at=row["created_at"].isoformat() if hasattr(row["created_at"],"isoformat") else str(row["created_at"]))
        return result
    except Exception:
        return None
