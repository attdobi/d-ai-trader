"""Review or apply the audited selective-opportunity policy repair.

Dry-run by default. --apply commits new prompt versions and deactivates only
matching blanket-veto memories. --show-backup BATCH reads the rollback snapshot.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json

from policy_graph.repair_opportunities import AGENTS, ACTION, RepairConflict, read_backup, repair


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--apply", action="store_true", help="Commit the reviewed policy repair")
    parser.add_argument("--expect", action="append", default=[], metavar="AGENT=VERSION")
    parser.add_argument("--show-backup", metavar="BATCH", help="Read the rollback snapshot; no writes")
    args = parser.parse_args(argv)
    if args.apply and args.show_backup:
        parser.error("--show-backup cannot be combined with --apply")
    expected = {}
    for item in args.expect:
        agent, sep, version = item.partition("=")
        if not sep or agent not in AGENTS or not version.isdigit():
            parser.error("--expect must be DeciderAgent=VERSION or FeedbackAgent=VERSION")
        expected[agent] = int(version)
    # Only the production entry point imports local configuration. It must never
    # silently repair a fallback database when the operator intended Postgres.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import config
            from prompt_manager import refresh_latest_policy_graph, set_active_prompt_version
        if config.engine.dialect.name != "postgresql":
            raise SystemExit("Postgres is required; refusing to use a fallback database")
        if args.show_backup:
            result = read_backup(config.engine, args.config_hash, args.show_backup)
        else:
            result = repair(config.engine, args.config_hash, set_active_prompt_version,
                            apply=args.apply, expected_versions=expected)
            if result["applied"]:
                refresh_latest_policy_graph(args.config_hash,
                                            [c["agent_type"] for c in result["journal"]["policies"]],
                                            materialized_by=ACTION)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except RepairConflict as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # Driver exception strings can include credentials or SQL parameters.
        raise SystemExit(f"Repair failed ({type(exc).__name__}); transaction was rolled back") from None


if __name__ == "__main__":
    main()
