"""Preview or explicitly run a bounded paired policy replay; never imports the trader.

Examples (preview is the default and makes no model calls):
  ./dai/bin/python learning_replay.py --input-id 148 --candidate-version 60
  ./dai/bin/python learning_replay.py --input-id 148 --candidate-version 60 \
      --assembly-mode full_policy --max-calls 2 --execute

This reads the existing local configuration silently. Prompts, keys and database
URLs are never printed. Paid execution needs --execute; no orders or policy
activation are possible. The map can read completed results from the local DB.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json

from policy_graph.learning_replay import MODES, ReplayError, preview_comparison, run_comparison
from policy_graph.learning_replay_client import make_openai_runner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-id", type=int, action="append", required=True, dest="source_input_ids")
    parser.add_argument("--candidate-version", type=int, required=True)
    parser.add_argument("--config-hash")
    parser.add_argument("--assembly-mode", choices=MODES, default="captured_subgraph_edits")
    parser.add_argument("--model", help="Optional explicit model override, identical on both sides")
    parser.add_argument("--reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--horizon", type=int, choices=(1, 3, 5), default=3)
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--max-output-tokens", type=int, default=3000)
    parser.add_argument("--expect-cohort-hash")
    parser.add_argument("--execute", action="store_true", help="Permit the paid model calls described by preview")
    args = parser.parse_args(argv)
    try:
        # Config never imports the trader, but its startup messages are not part
        # of the public replay report. Do not expose driver exceptions/URLs.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import config
        cfg = args.config_hash or config.get_current_config_hash()
        options = dict(source_input_ids=args.source_input_ids, candidate_version=args.candidate_version,
                       assembly_mode=args.assembly_mode, model=args.model, reasoning_effort=args.reasoning_effort,
                       max_calls=args.max_calls, outcome_spec={"horizon": args.horizon,
                       "basis": "prospective_ledger_fixed_horizon"})
        preview = preview_comparison(config.engine, cfg, **options)
        if not args.execute or not preview["compatible"]:
            print(json.dumps(preview, indent=2))
            return 0 if preview["compatible"] else 2
        runner = make_openai_runner(engine=config.engine, config_hash=cfg,
                                    max_completion_tokens=args.max_output_tokens)
        result = run_comparison(config.engine, cfg, runner=runner, **options,
                                expected_cohort_hash=args.expect_cohort_hash or preview["cohort_hash"])
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["status"] == "ok" else 3
    except ReplayError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except Exception as exc:
        # OpenAI/driver exception messages may contain sensitive request data.
        print(json.dumps({"error": type(exc).__name__, "note": "Replay unavailable; inspect local configuration"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
