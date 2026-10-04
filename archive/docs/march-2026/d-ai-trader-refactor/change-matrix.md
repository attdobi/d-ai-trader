# Refactor Change Matrix

| Area | Current Risk | Planned Change | Expected Benefit | New Functionality Unlocked |
|---|---|---|---|---|
| Run context | Hidden global mutation in orchestrator/decider coupling | Explicit `RunContext` propagation | Deterministic runs, fewer side effects | Multi-run replay and deterministic debugging |
| Data isolation | Some holdings/safety queries not fully `config_hash` scoped | Enforce config scoping in repositories/queries | Parallel config safety | True multi-strategy operation on one DB |
| Execution boundary | Decisioning and live execution mixed | Single live execution pipeline via `TradingInterface` | Consistent risk gating | Safe dry-run and live parity checks |
| Symbol handling | Inconsistent symbol mapping across modules | One canonical normalization policy | Fewer false skips and sell misses | Better broker portability |
| Portfolio snapshots | Snapshot writes/reads can be inconsistent by config | Standardized `portfolio_history` contract | Accurate charts and feedback inputs | Cross-strategy performance analytics |
| Startup model config | Repeated import-time model setting and noisy logs | Centralized startup config initialization | Predictable startup behavior | Config profile switching with less operator error |
| Schwab token lifecycle | Refresh failures are noisy and ambiguous | Token preflight + explicit remediation messages | Faster incident recovery | Token health dashboard panel/CLI |
| Logging and observability | Sensitive raw payload logs and inconsistent context | Structured logging with redaction + correlation IDs | Safer logs, faster triage | Better run-level audit reports |
| Code shape | Duplicate functions and unreachable branches | Dead code removal + extraction into cohesive modules | Lower regression risk | Faster onboarding and feature throughput |
| Automated tests | Mostly script-style tests, low assertion density | Add assertion-based critical-path tests | Catch regressions earlier | Confidence to ship incremental functionality |

## Priority Recommendation
- P0: data isolation, execution boundary, portfolio snapshot integrity.
- P1: ticker normalization, startup/model initialization, token lifecycle hardening.
- P2: structural cleanup, logging polish, broader test expansion.
