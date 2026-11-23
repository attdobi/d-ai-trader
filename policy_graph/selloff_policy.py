"""Operator-reviewed selloff and fill-attribution instructions for active prompts and new baselines."""
from .model import FIELDS


MIN_DECLINE_PCT = 8
MIN_DOLLAR_VOLUME = 10_000_000
SELLOFF_REVIEW_ID = "DA.code.selloff_review"
SELLOFF_REVIEW_HEADER = (
    "# LARGE SELLOFF REVIEW\n"
    f"Unheld names in the supplied momentum recap fell at least {MIN_DECLINE_PCT}% from the prior close "
    f"with observed price × session volume of at least ${MIN_DOLLAR_VOLUME:,}. "
    "Include each ticker in considered with verdict buy, watch or reject, a concrete reason and cited rules. "
    "Put proposed BUYs in decisions as well. Verify reversal, risk limits and re-entry eligibility."
)


SECTIONS = {
    "SummarizerAgent": (
        "strategy_directives", "Selloff evidence",
        "When a source shows a sharp decline, put the ticker, price move, reference price or period, "
        "and observation time in insights when available. Distinguish a broad or sector selloff from "
        "company-specific news. Report visible evidence of stabilization or continued selling and "
        "identify its source. Leave missing baselines and causes unknown.",
    ),
    "DeciderAgent": (
        "strategy_directives", "Large selloff review",
        "For every ticker in LARGE SELLOFF REVIEW, include one considered row with a buy, watch or reject "
        "verdict, including names under re-entry quarantine. Use decision-time evidence to explain how the "
        "stock moved relative to its sector and whether support held. Cite the binding guideline. "
        "For a watch or rejection, state what would justify another review, such as the quarantine ending "
        "or a supported reclaim. For a buy, give the supported entry and stop. "
        "Apply [[Re-entry quarantine]], [[Day chase]] and [[Priced kill]] along with the other active "
        "controls. Inclusion on this list only requires an assessment.",
    ),
    "FeedbackAgent": (
        "soul", "Selloff and fill attribution",
        "Evaluate the agent’s trading P&L from matched entry and exit fills, quantities and fees. "
        "Report gaps in fill or fee evidence and identify estimates. A revised broker cost basis belongs "
        "in a separate reconciliation. For large selloffs, report paper outcomes separately from executed "
        "P&L and regular screener recall. Compare buys, watches, blocked entries and missing assessments "
        "using the same reference time and horizon. Give counts and pending outcomes. A later headline "
        "or rebound cannot establish what the agent knew at the decision. Require evidence across "
        "independent cases before proposing a change to an entry rule.",
    ),
}

DESCRIPTIONS = {
    "SummarizerAgent": "Identify what fell, when, and which source supports the move or recovery.",
    "DeciderAgent": "Explain each large selloff assessment, the binding rule and when to revisit it.",
    "FeedbackAgent": "Separate matched-fill performance from broker basis and missed selloff opportunities.",
}


def add_selloff_fields(agent, fields):
    result = dict(fields)
    if agent not in SECTIONS:
        return result
    field, title, body = SECTIONS[agent]
    heading = "## " + title
    original = fields.get(field) or ""
    lines = original.splitlines()
    if heading in lines:
        # Protect subsequent operator edits when the update is run again.
        body_start = lines.index(heading) + 1
        body_end = next((i for i in range(body_start, len(lines)) if lines[i].startswith("## ")), len(lines))
        if "\n".join(lines[body_start:body_end]).strip() != body:
            from .prompt_audit import AuditConflict
            raise AuditConflict(f"{agent} already has a different section named {title}")
        return result
    separator = "" if not original or original.endswith("\n\n") else "\n" if original.endswith("\n") else "\n\n"
    result[field] = f"{original}{separator}{heading}\n{body}\n"
    return result


def reviewed_spec(engine, config_hash):
    from . import prompt_audit
    with engine.connect() as conn:
        rows = prompt_audit._snapshot(conn, config_hash)["prompts"]
    agents = {}
    for row in rows:
        agent = row["agent_type"]
        fields = {field: row.get(field) or "" for field in FIELDS}
        agents[agent] = {
            "from_version": row["version"], "source_row_id": row["id"],
            "fields": add_selloff_fields(agent, fields),
            "description": DESCRIPTIONS.get(agent, ""),
            "classification": [DESCRIPTIONS[agent]] if agent in DESCRIPTIONS else [],
        }
    return {
        "schema_version": 1, "audit_id": "selloff-attribution-2026-11-23",
        "config_hash": config_hash, "agents": agents,
        "memory_actions": {"retire_ids": [], "insert": []},
    }
