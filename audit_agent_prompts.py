#!/usr/bin/env python3
"""Preview or atomically activate the reviewed agent policy audit. Never trades."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from policy_graph import prompt_audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source-hash", help="Exact source_hash from the reviewed preview")
    parser.add_argument("--spec-hash", help="Exact spec_hash from the reviewed preview")
    parser.add_argument("--output", type=Path, help="Write detailed JSON to this local path")
    args = parser.parse_args(argv)
    spec = prompt_audit.load_spec()
    if args.config_hash != spec["config_hash"]:
        parser.error("The reviewed audit belongs to a different configuration")
    if args.apply and (not args.source_hash or not args.spec_hash):
        parser.error("Activation requires both hashes from the reviewed preview")
    # Local config can emit broker startup details. Keep those out of output.
    # Importing this CLI/module itself does not load configuration or clients.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from config import engine
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Use the existing Postgres database; no fallback database is allowed")
    if args.apply:
        from prompt_manager import set_active_prompt_version, refresh_latest_policy_graph
        result = prompt_audit.apply(engine, args.config_hash, set_active_prompt_version,
                                    expected_source_hash=args.source_hash, expected_spec_hash=args.spec_hash,
                                    spec=spec)
        # Only after the audited transaction commits may the latest mirrors move.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result["mirrors"] = refresh_latest_policy_graph(args.config_hash, list(spec["agents"]),
                                                           materialized_by="operator_prompt_audit")
        summary = {"applied": True, "batch_id": result["batch_id"], "policies": result["policies"],
                   "retired_memories": len(spec["memory_actions"]["retire_ids"]),
                   "new_memories": len(spec["memory_actions"]["insert"]), "mirrors": result["mirrors"]}
    else:
        result = prompt_audit.preview(engine, args.config_hash, spec=spec)
        summary = {k: v for k, v in result.items() if k != "agents"}
        summary["agents"] = [{k: v for k, v in a.items() if k != "diff"} for a in result["agents"]]
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
        args.output.chmod(0o600)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Driver exception strings may contain connection details; do not echo them.
        print(json.dumps({"error": type(exc).__name__, "message": "Audit did not complete; inspect the local reviewed inputs and database state."}))
        raise SystemExit(1)
