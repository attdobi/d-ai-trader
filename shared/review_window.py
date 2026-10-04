"""Balanced prompt-review history window.

The Prompt Lab generator, the policy-graph drafter and the weekly feedback prompt all
read recent ``prompt_change_reviews`` rows to learn from past verdicts. They used to
select ``ORDER BY (human_verdict IS NOT NULL) DESC, created_at DESC LIMIT 8`` — with
every live review human-labeled, an unclicked critic verdict could never reach the
next prompt. The window now reserves slots for both signals:

  * up to ``human_quota`` (5) newest human-labeled rows (the RLHF signal),
  * up to ``critic_quota`` (3) newest UNLABELED genuine critic verdicts (an LLM
    judgment: not a heuristic auto-verdict, confidence > 0),
  * filled to ``limit`` (8) by recency from whatever else the filter admits,

returned newest-first. Outage rows (confidence 0 and not auto) carry no judgment and
are excluded by default.

The SQL is portable (Postgres + SQLite) so the window is testable in memory.
"""

from __future__ import annotations

import json

HUMAN_QUOTA = 5
CRITIC_QUOTA = 3
WINDOW_LIMIT = 8

# An LLM judgment: not a heuristic auto-verdict, not an outage (confidence 0).
GENUINE_SQL = "(COALESCE(critic_auto, FALSE) = FALSE AND COALESCE(critic_confidence, 0) > 0)"
# Anything but an outage row: auto-verdicts stay (they are labeled as heuristic).
NOT_OUTAGE_SQL = "(COALESCE(critic_confidence, 0) > 0 OR COALESCE(critic_auto, FALSE))"

_PRIVATE = ("_rid", "_created_at", "_labeled", "_genuine", "_rn")


def select_balanced(rows, limit=WINDOW_LIMIT, human_quota=HUMAN_QUOTA, critic_quota=CRITIC_QUOTA):
    """Pick the window from ``rows`` (dicts, newest-first, each carrying ``_labeled`` and
    ``_genuine`` flags). Returns the picked rows newest-first."""
    limit = max(0, int(limit))
    rows = list(rows or [])
    labeled = [i for i, r in enumerate(rows) if r.get("_labeled")]
    pending_genuine = [i for i, r in enumerate(rows) if not r.get("_labeled") and r.get("_genuine")]
    picked = labeled[:max(0, min(int(human_quota), limit))]
    room = max(0, min(int(critic_quota), limit - len(picked)))
    picked += pending_genuine[:room]
    taken = set(picked)
    for i in range(len(rows)):
        if len(picked) >= limit:
            break
        if i not in taken:
            picked.append(i)
            taken.add(i)
    return [rows[i] for i in sorted(picked)]


def _review_date(value):
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date().isoformat()
        except Exception:
            pass
    return str(value)[:10]


def _sections(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def fetch_review_window(conn, config_hash, *, agent_type=None, genuine_only=False,
                        exclude_outages=True, reason_chars=300, limit=WINDOW_LIMIT,
                        human_quota=HUMAN_QUOTA, critic_quota=CRITIC_QUOTA):
    """Run the windowed query on ``conn`` and return the balanced rows as plain dicts
    (newest-first). Raises on a DB error — callers keep their own fail-safe."""
    from sqlalchemy import text  # call-time import: never bind a stubbed module at import

    limit = max(0, int(limit))
    params = {"h": config_hash, "lim": limit, "chars": max(1, int(reason_chars))}
    clauses = ""
    if agent_type:
        clauses += " AND agent_type = :a"
        params["a"] = agent_type
    if exclude_outages:
        clauses += f" AND {NOT_OUTAGE_SQL}"
    if genuine_only:
        clauses += f" AND {GENUINE_SQL}"
    labeled_sql = "CASE WHEN human_verdict IS NOT NULL THEN 1 ELSE 0 END"
    genuine_sql = f"CASE WHEN {GENUINE_SQL} THEN 1 ELSE 0 END"
    # Every partition (labeled / unlabeled-genuine / unlabeled-other) keeps its newest
    # `limit` rows, so the quota picks and the recency fill are both exact.
    rows = conn.execute(text(f"""
        SELECT * FROM (
            SELECT created_at, agent_type, from_version, to_version,
                   critic_verdict, COALESCE(critic_auto, FALSE) AS critic_auto,
                   ROUND(CAST(critic_confidence AS NUMERIC), 2) AS critic_confidence,
                   SUBSTR(COALESCE(critic_reason, ''), 1, :chars) AS critic_reason,
                   human_verdict, human_agrees_critic, human_sections,
                   realized_winrate_delta, realized_pnl,
                   id AS _rid, created_at AS _created_at,
                   {labeled_sql} AS _labeled, {genuine_sql} AS _genuine,
                   ROW_NUMBER() OVER (
                       PARTITION BY {labeled_sql}, {genuine_sql}
                       ORDER BY created_at DESC, id DESC) AS _rn
            FROM prompt_change_reviews
            WHERE config_hash = :h{clauses}
        ) w
        WHERE _rn <= :lim
        ORDER BY (CASE WHEN _created_at IS NULL THEN 1 ELSE 0 END), _created_at DESC, _rid DESC
    """), params).fetchall()
    dicts = [dict(r._mapping) for r in rows]
    window = select_balanced(dicts, limit=limit, human_quota=human_quota, critic_quota=critic_quota)
    out = []
    for d in window:
        d = {k: v for k, v in d.items() if k not in _PRIVATE}
        d["review_date"] = _review_date(d.pop("created_at", None))
        d["critic_auto"] = bool(d.get("critic_auto"))
        if d.get("human_agrees_critic") is not None:   # SQLite hands back 0/1
            d["human_agrees_critic"] = bool(d["human_agrees_critic"])
        d["human_sections"] = _sections(d.get("human_sections"))
        out.append({"review_date": d.pop("review_date"), **d})
    return out
