"""Decider memory — two tiers.

LONG-TERM (structured, persistent): distilled lessons/rules/patterns earned from P&L,
stored in the `decider_memory` table (tagged, weighted, prunable) and retrieved by
relevance each cycle. Replaces the ever-growing MEMORY.md text blob as the source of truth;
the feedback agent and the human both write to it.

SHORT-TERM (working memory): a rolling recap of the decider's OWN recent activity — what it
bought/sold/rejected and how it is going — computed each cycle from `trade_decisions`.
This is what gives continuity and stops churn/repetition within a session.

Public API:
    ensure_table()
    add_memory(config_hash, content, kind=, tags=, ticker=, source=, weight=)
    get_relevant_memories(config_hash, tickers=None, limit=None) -> list[dict]
    format_long_term_memory(memories) -> str            # prompt block
    build_working_memory(config_hash, recent_cycles=6) -> str   # prompt block
"""
import os
import json
import logging
from sqlalchemy import text
from config import engine

logger = logging.getLogger(__name__)

_LT_LIMIT = int(os.getenv("DAI_MEMORY_LT_LIMIT", "14"))

_DDL = """
CREATE TABLE IF NOT EXISTS decider_memory (
    id          SERIAL PRIMARY KEY,
    config_hash TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    kind        TEXT DEFAULT 'lesson',   -- lesson | rule | pattern | mistake
    tags        TEXT[],
    ticker      TEXT,
    content     TEXT NOT NULL,
    source      TEXT DEFAULT 'feedback', -- feedback | human | auto | seed
    weight      REAL DEFAULT 1.0,
    active      BOOLEAN DEFAULT TRUE
)
"""


def ensure_table():
    try:
        with engine.begin() as conn:
            conn.execute(text(_DDL))
    except Exception as exc:
        logger.warning("decider_memory ensure_table failed: %s", exc)


def add_memory(config_hash, content, kind="lesson", tags=None, ticker=None, source="feedback", weight=1.0):
    """Insert a long-term memory. De-dupes on identical active content per config."""
    if not content or not str(content).strip():
        return
    content = str(content).strip()
    try:
        with engine.begin() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM decider_memory WHERE config_hash=:c AND active AND content=:ct LIMIT 1"
            ), {"c": config_hash, "ct": content}).fetchone()
            if exists:
                return
            conn.execute(text("""
                INSERT INTO decider_memory (config_hash, kind, tags, ticker, content, source, weight)
                VALUES (:c, :k, :t, :tk, :ct, :s, :w)
            """), {
                "c": config_hash, "k": kind, "t": list(tags) if tags else None,
                "tk": (ticker.upper() if ticker else None), "ct": content, "s": source, "w": float(weight),
            })
    except Exception as exc:
        logger.warning("decider_memory add_memory failed: %s", exc)


def get_relevant_memories(config_hash, tickers=None, limit=None):
    """Top lessons for this cycle: ticker-relevant first, then heaviest, then most recent."""
    limit = limit or _LT_LIMIT
    tks = [t.upper() for t in (tickers or []) if t]
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT content, kind, ticker, weight FROM decider_memory
                WHERE config_hash = :c AND active = TRUE
                ORDER BY (CASE WHEN ticker = ANY(:tks) THEN 1 ELSE 0 END) DESC,
                         weight DESC, created_at DESC
                LIMIT :lim
            """), {"c": config_hash, "tks": tks, "lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        logger.warning("decider_memory get_relevant_memories failed: %s", exc)
        return []


def format_long_term_memory(memories):
    if not memories:
        return ""
    lines = ["# LESSONS (long-term memory — hard rules earned from P&L; OBEY them):"]
    for m in memories:
        tk = f" ({m['ticker']})" if m.get("ticker") else ""
        kind = (m.get("kind") or "lesson")
        lines.append(f"- [{kind}]{tk} {m['content']}")
    return "\n".join(lines)


def build_working_memory(config_hash, recent_cycles=6):
    """Short-term: a recap of the decider's own recent cycles (actions + why)."""
    lines = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT timestamp, data FROM trade_decisions
                WHERE config_hash = :c
                ORDER BY id DESC LIMIT :n
            """), {"c": config_hash, "n": recent_cycles}).fetchall()
        for r in rows:
            data = r.data if isinstance(r.data, list) else json.loads(r.data)
            when = r.timestamp.strftime("%m/%d %H:%M") if r.timestamp else "recent"
            acts, cash_reason = [], None
            for el in data:
                if not isinstance(el, dict) or el.get("kind") == "considered_audit":
                    continue
                a = (el.get("action") or "").lower()
                tk = el.get("ticker")
                st = (el.get("action") and (el.get("execution_status") or "").lower()) or ""
                if a in ("buy", "sell") and tk:
                    mark = "" if st == "filled" else (f"[{st}]" if st else "[unconfirmed]")
                    acts.append(f"{a.upper()} {tk}{mark}")
                elif a == "hold" and tk == "CASH":
                    cash_reason = el.get("reason")
            if acts:
                lines.append(f"- {when}: " + ", ".join(acts[:6]))
            elif cash_reason:
                lines.append(f"- {when}: CASH-hold — {str(cash_reason)[:110]}")
    except Exception as exc:
        logger.warning("decider_memory build_working_memory failed: %s", exc)
        return ""
    if not lines:
        return ""
    return ("# RECENT ACTIVITY (short-term working memory — your last few cycles; do NOT repeat "
            "mistakes or churn what you just did):\n" + "\n".join(lines))


if __name__ == "__main__":
    import sys
    ch = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CURRENT_CONFIG_HASH", "9ea09b9as")
    ensure_table()
    print(format_long_term_memory(get_relevant_memories(ch)) or "(no long-term memories)")
    print()
    print(build_working_memory(ch) or "(no recent activity)")
