# Archive

Files that the running system no longer uses, moved here on 2026-10-04 with `git mv`, so `git log --follow <path>` still shows their history.

Every file here was checked by two independent reviews before it moved. One searched for imports, subprocess calls, dashboard routes, shell scripts, tests and docs that still reach the file. The other judged whether an operator would still run or read it against today's schema and launcher. A file moved only when both said it was unused. Files where the two disagreed stayed at the repo root.

Nothing here is imported by `dashboard_server.py`, `d_ai_trader.py`, `init_database.py` or the test suite.

## What is here

| Folder | Contents | Why archived |
|---|---|---|
| `scripts/` | One-off migrations and fixes (`fix_*.py`, `migrate_database_for_parallel_runs.py`, `reset_config.py`, `cleanup_portfolio_history.py`, `backfill_trade_categories.py`), early demos (`demonstrate_prompt_evolution.py`, `update_prompt_example.py`, `update_day_trading_prompts.py`, `initialize_prompts_old.py`), a June A/B cost test, `reconcile_executions.py` (superseded by `reconcile_execution_status.py`), `manual_price_update.py`, `get_schwab_account.py`, `run_feedback_analysis.py`, `config_mode.py`, and the 2025 live launchers `start_live_trading.sh`, `start_schwab_one_trade.sh`, `start_schwab_readonly.sh`, `fix_reset_v0.sh` | Already applied, superseded, or written against tables and prompt formats that have since changed |
| `policy_ops/` | `apply_event_risk_policy.py`, `apply_plain_rules.py`, `apply_plain_gates.py`, `apply_whole_share_rule.py` | The September 2026 policy-graph operator passes. They are idempotent and kept as provenance for Decider v28 to v42. |
| `docs/root/` | 2025 setup and process docs (`AUTOMATION_README.md`, `FEEDBACK_SYSTEM.md`, `GO_LIVE_CHECKLIST.md`, `SCHWAB_API_SETUP.md`, `SCHWAB_READONLY_TEST.md`, `SETUP_DEPENDENCIES.md`, `IMPLEMENTATION_SUMMARY.md`, `FRONTEND_TASKS.md`) | They describe a daily feedback job, scripts and flags that no longer exist. The main README replaces them, and `SCHWAB_SETUP.md` stays at the root as the Schwab guide. |
| `docs/march-2026/` | The March 2026 refactor plan, split plan, backlog, handoff and the X1/X2 work logs, plus the `d-ai-trader-refactor/` notes | Planning notes for work that has shipped |
| `legacy/` | `prompts/` (the gpt-pro and standard prompt profiles), `tests/test_prompt_loading.py`, the July 2025 copies from `backups/`, and the October 2025 template backup | No code reads `DAI_PROMPT_PROFILE` any more, so the profiles and their tests were dead. Those were the 9 tests that had been failing and deselected. |

`scripts/fix_constraints_only.py` joined them later the same day. Its `DROP DEFAULT` on `config_hash` had never been applied, so `init_database.py` now runs it as an idempotent migration on every start (`holdings`, `summaries` and `trade_decisions`, Postgres only).

## Running something from here

Scripts here import modules from the repo root, so run them from the root with the root on the path:

```bash
PYTHONPATH=. ./dai/bin/python archive/scripts/<script>.py --help
```

The `policy_ops/` scripts add the repo root to the path themselves, so plain `./dai/bin/python archive/policy_ops/<script>.py --dry-run` works. Always dry-run first. Several scripts in `scripts/` write to the database directly, and some do so with hardcoded config hashes.

## Not here on purpose

These looked unused to one review but stay at the root as hand-run operator tools:

- `check_order_status.py`, `effective_funds_probe.py` and `verify_schwab_token.py`, which are read-only Schwab diagnostics.
- `reconcile_execution_status.py`, which reconciles decisions against 60 days of Schwab orders. It writes its rollback copies to `backups/`.
- `start_schwab_live_view.sh` with `run_schwab_streaming.py` and `schwab_streaming.py`, the read-only dashboard launcher.
- `backfill_version_outcomes.py`, which the Thursday feedback job imports.
