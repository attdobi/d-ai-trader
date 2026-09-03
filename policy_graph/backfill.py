"""CLI backfill: mirror every prompt_versions row of one config hash to disk.

    ./dai/bin/python -m policy_graph.backfill --config-hash 9ea09b9as [--agent DeciderAgent]
                                             [--dry-run] [--verify-only] [--force] [--repo-root DIR]
    ./dai/bin/python -m policy_graph.backfill --baseline [--verify-only]     # committed v0, no database

Prints one line per version, e.g.

    DeciderAgent v19  created  23 nodes  +1 ~0 −2  roundtrip ok  soul:inherited@54a50e5e

and exits non-zero on any RoundTripError (or a verify mismatch). The hash comes from the flag only.
`config` (for the SQLAlchemy engine) is imported lazily inside main() — the package itself never
imports it. Read-only on the database; writes only under <repo-root>/agents/*/policy-graph/<hash>/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import code_blocks, service
from .model import AGENT_PREFIX


def _fmt_delta(delta: dict | None) -> str:
    d = delta or {}
    return f"+{d.get('added', 0)} ~{d.get('changed', 0)} −{d.get('removed', 0)}"


def _fmt_sources(cur, row: dict) -> str:
    parts = []
    for f in ("soul", "memory"):
        fm = ((cur.manifest.get("fields") or {}).get(f) or {}) if cur is not None else {}
        if fm.get("inherited"):
            sha = fm.get("inherited_git_sha") or fm.get("inherited_resolution") or "worktree"
            parts.append(f"{f}:inherited@{sha}")
        elif not row.get(f):
            parts.append(f"{f}:empty")
    return "  ".join(parts)


def _line(agent: str, version: int, action: str, node_count: int, delta: dict | None, roundtrip: str,
          sources: str) -> str:
    return (f"{agent} v{version}  {action}  {node_count} nodes  {_fmt_delta(delta)}  "
            f"roundtrip {roundtrip}  {sources}").rstrip()


def run(engine, config_hash: str, *, repo_root: Path, is_margin_account: bool, agents: list,
        dry_run: bool = False, verify_only: bool = False, force: bool = False, out=sys.stdout,
        defaults_root: Path | None = None) -> int:
    """Returns the process exit code (0 ok, 1 round-trip/verify failure, 2 nothing to do)."""
    from . import store
    failures = 0
    total = 0
    for agent in agents:
        ctx = service._Ctx(engine, config_hash, repo_root, is_margin_account, defaults_root=defaults_root)
        rows = ctx.rows(agent)
        if not rows:
            print(f"{agent}  (no prompt_versions rows for config {config_hash})", file=out)
            continue
        prev = None
        for row in rows:
            total += 1
            n = row["version"]
            action, roundtrip, error = None, "ok", None
            if verify_only:
                cur = ctx.read_version(agent, n)
                action = "present" if ctx.is_materialized(agent, n) else "missing"
                roundtrip = ctx.roundtrip(agent, n, row)
                if roundtrip != "ok":
                    failures += 1
                    error = ctx.read_errors.get((agent, n))
            elif dry_run:
                action = "would-" + service.plan_action(ctx, config_hash, agent, n)
                cur = ctx.read_version(agent, n)
                roundtrip = ctx.roundtrip(agent, n, row) if ctx.is_materialized(agent, n) else "n/a"
            else:
                try:
                    res = service._ensure(ctx, agent, row, materialized_by="backfill", force=force)
                    action, roundtrip = res["action"], res["roundtrip"]
                except store.RoundTripError as exc:
                    failures += 1
                    action, roundtrip, error = "FAILED", "mismatch", str(exc)
                except store.StoreBusy as exc:
                    failures += 1
                    action, roundtrip, error = "BUSY", "n/a", str(exc)
                cur = ctx.read_version(agent, n)
            vd = service._safe_diff(prev, cur)
            delta = service._delta_of(vd) if vd is not None else (cur.manifest.get("delta_vs_prev") if cur else None)
            print(_line(agent, n, action, len(cur.nodes) if cur is not None else 0, delta, roundtrip,
                        _fmt_sources(cur, row)), file=out)
            if error:
                print(f"    {error}", file=out)
            prev = cur if cur is not None else prev
    print(f"code_sha {code_blocks.CODE_SHA}  versions {total}  failures {failures}", file=out)
    if total == 0:
        return 2
    return 1 if failures else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m policy_graph.backfill", description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", default=None, help="config hash whose prompt_versions rows are mirrored")
    p.add_argument("--baseline", action="store_true",
                   help="write the committed baseline instead: agents/*/policy-graph/baseline/v0 from "
                        "initialize_prompts.DEFAULT_PROMPTS (no database)")
    p.add_argument("--agent", choices=sorted(AGENT_PREFIX), default=None, help="one agent only (default: all three)")
    p.add_argument("--dry-run", action="store_true", help="print what each version would do; write nothing")
    p.add_argument("--verify-only", action="store_true", help="only compare existing dirs with the rows (no writes)")
    p.add_argument("--force", action="store_true", help="rebuild every version even when unchanged")
    p.add_argument("--repo-root", default=None, help="repo root holding agents/ (default: this checkout)")
    p.add_argument("--defaults-root", default=None,
                   help="checkout used to resolve inherited SOUL/MEMORY defaults via git (default: --repo-root)")
    p.add_argument("--margin", action="store_true", help="evaluate code-block conditions for a margin account")
    args = p.parse_args(argv)

    if args.baseline:
        from .baseline import verify_baseline, write_baseline
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
        agents = [args.agent] if args.agent else list(AGENT_PREFIX)
        if args.verify_only:
            problems = verify_baseline(repo_root, agents=agents)
            for agent, problem in problems:
                print(f"{agent}  baseline v0  {problem}")
            print(f"baseline versions {len(agents)}  failures {len(problems)}")
            return 1 if problems else 0
        for agent, action, path in write_baseline(repo_root, agents=agents, is_margin_account=bool(args.margin)):
            print(f"{agent} v0  {action}  {path}")
        problems = verify_baseline(repo_root, agents=agents)
        return 1 if problems else 0
    if not args.config_hash:
        p.error("--config-hash is required (or use --baseline)")

    import config  # lazy: the only place the policy_graph package touches config
    engine = config.engine
    is_margin = bool(args.margin or getattr(config, "IS_MARGIN_ACCOUNT", False))
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    agents = [args.agent] if args.agent else list(AGENT_PREFIX)
    defaults_root = Path(args.defaults_root).resolve() if args.defaults_root else None
    return run(engine, args.config_hash, repo_root=repo_root, is_margin_account=is_margin, agents=agents,
               dry_run=args.dry_run, verify_only=args.verify_only, force=args.force, defaults_root=defaults_root)


if __name__ == "__main__":
    sys.exit(main())
