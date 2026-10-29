#!/usr/bin/env python3
"""Preview/apply the reviewed visual-context supplement; never invokes trading."""
import argparse
import contextlib
import io
import json
from pathlib import Path

from policy_graph import prompt_audit
from policy_graph.model import FIELDS
from policy_graph.visual_policy import add_visual_fields, DESCRIPTION, CLASSIFICATION


def reviewed_spec(engine, config_hash):
    with engine.connect() as conn:
        snapshot = prompt_audit._snapshot(conn, config_hash)
    agents = {}
    for row in snapshot["prompts"]:
        fields = {field: row.get(field) or "" for field in FIELDS}
        agents[row["agent_type"]] = {
            "from_version": row["version"], "source_row_id": row["id"],
            "fields": add_visual_fields(row["agent_type"], fields),
            "classification": CLASSIFICATION, "description": DESCRIPTION}
    return {"schema_version": 1, "audit_id": "visual-context-2026-10-29",
            "config_hash": config_hash, "agents": agents, "memory_actions": {}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source-hash")
    parser.add_argument("--spec-hash")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.apply and (not args.source_hash or not args.spec_hash):
        parser.error("Activation requires both hashes from the reviewed preview")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from config import engine
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The existing Postgres database is required")
    spec = reviewed_spec(engine, args.config_hash)
    if args.apply:
        from prompt_manager import set_active_prompt_version, refresh_latest_policy_graph
        result = prompt_audit.apply(engine, args.config_hash, set_active_prompt_version, spec=spec,
                                    expected_source_hash=args.source_hash, expected_spec_hash=args.spec_hash)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mirrors = refresh_latest_policy_graph(args.config_hash, list(spec["agents"]), materialized_by="visual_context_audit")
        result["mirrors"] = {agent: value if value in ("synced", "unchanged") else "check local mirror"
                             for agent, value in mirrors.items()}
        summary = {"applied": True, "batch_id": result["batch_id"], "policies": result["policies"],
                   "mirrors": result["mirrors"]}
    else:
        result = prompt_audit.preview(engine, args.config_hash, spec=spec)
        summary = {key: value for key, value in result.items() if key != "agents"}
        summary["agents"] = [{key: value for key, value in row.items() if key != "diff"} for row in result["agents"]]
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2) + "\n")
        args.output.chmod(0o600)
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Visual-policy update did not complete; inspect local audit state."}))
        raise SystemExit(1)
