"""Paper experiments using the memories and scores captured with a saved decision."""
from __future__ import annotations

import json
import math
import re

from sqlalchemy import text

from policy_graph.learning_replay import ReplayError
from policy_router.decisions import MAX_SKIP_PROBABILITY

MEMORY_HEADER = "# LESSONS (long-term evidence — subordinate to the active policy and opportunity charter):\n"
INDEX_HEADER = "GUIDELINE INDEX (id — title):\n"
BODY_ID = re.compile(r" ⟨(DA\.ltm\.\d+)(?: · [^⟩\n]*)?⟩$")
INDEX_ID = re.compile(r"^(DA\.ltm\.\d+) — (.+)$")


def memory_lines(source):
    """Return exact body/index lines, validating their equality to the recorded served set."""
    prompt = source["user_prompt"]
    if prompt.count(MEMORY_HEADER) != 1 or prompt.count(INDEX_HEADER) != 1:
        raise ReplayError("unique saved memory block and citation index required")
    start = prompt.index(MEMORY_HEADER) + len(MEMORY_HEADER)
    index_start = prompt.index(INDEX_HEADER) + len(INDEX_HEADER)
    if start >= index_start:
        raise ReplayError("saved prompt sections are out of order")
    body = {}
    titles = {}
    for line in prompt[start:].splitlines(keepends=True):
        if not line.startswith("- ["):
            break
        match = BODY_ID.search(line.rstrip("\r\n"))
        if match is None or match[1] in body:
            raise ReplayError("ambiguous saved memory line")
        body[match[1]] = line
    for line in prompt[index_start:].splitlines(keepends=True):
        if not line.strip():
            break
        match = INDEX_ID.fullmatch(line.rstrip("\r\n"))
        if match:
            if match[1] in titles:
                raise ReplayError("duplicate saved memory index line")
            titles[match[1]] = line
    recorded = {f"DA.ltm.{i}" for i in json.loads(source["ltm_ids"] or "[]")}
    if not recorded or set(body) != recorded or set(titles) != recorded:
        raise ReplayError("memory block, index and saved memory IDs differ")
    return body, titles


def routed_prompt(engine, config_hash, source):
    """Apply the production omission guard to a complete contemporaneous shadow score set."""
    body, titles = memory_lines(source)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT nodes_json,comparison_json FROM policy_router_comparisons
            WHERE config_hash=:h AND run_id=:run AND source_input_id=:i AND prompt_version=:v
              AND source_kind='live' AND status='ok'
        """), {
            "h": config_hash, "run": source["run_id"], "i": source["id"], "v": source["prompt_version"],
        }).mappings().all()
    if len(rows) != 1 or json.loads(rows[0]["comparison_json"]).get("applied"):
        raise ReplayError("one scored cycle with a full saved incumbent is required")
    nodes = [
        node for node in json.loads(rows[0]["nodes_json"])
        if node.get("kind") == "ltm" and node.get("served_in_prompt") is True
    ]
    if len(nodes) != len(body) or set(body) != {n["node_id"] for n in nodes}:
        raise ReplayError("recorded score coverage differs from the captured memory set")
    omitted = []
    for node in nodes:
        probability = node.get("decisions_p")
        choice = node.get("decisions_choice")
        if (type(probability) not in (int, float) or not math.isfinite(probability)
                or not 0 <= probability <= 1 or choice not in {"include", "exclude"}):
            raise ReplayError("recorded router answer is incomplete")
        if choice == "exclude" and probability <= MAX_SKIP_PROBABILITY:
            omitted.append(node["node_id"])
    if not omitted or len(omitted) == len(body):
        raise ReplayError("production omission guard would leave prompt unchanged")
    prompt = source["user_prompt"]
    for ident in omitted:
        for line in (body[ident], titles[ident]):
            if prompt.count(line) != 1:
                raise ReplayError("ambiguous saved memory span")
            prompt = prompt.replace(line, "", 1)
    return prompt, sorted(omitted)
