# D-AI-Trader Refactor Plan

## 1. Objective
Stabilize live trading behavior, make run isolation deterministic, reduce hidden coupling, and create a safer platform for adding new functionality.

## 2. Current State Summary
Primary issues found in the current codebase:
- Mixed responsibilities between decisioning, simulation state updates, and live execution.
- Some portfolio/safety queries are not consistently scoped by `config_hash`.
- Duplicate and dead code paths in critical execution logic.
- Inconsistent ticker normalization across modules.
- Startup side effects (model setting, logging) repeated across import paths.
- Limited automated regression coverage for live-critical behavior.

## 3. Refactor Principles
- Keep external behavior stable unless explicitly improved.
- Move risk-sensitive logic behind one execution boundary.
- Make all state mutations config-scoped and testable.
- Replace implicit global state with explicit run context.
- Improve observability while removing sensitive payload logging.

## 4. Target Architecture (Incremental)
- `orchestration/`: scheduling and run context only.
- `decisioning/`: prompt assembly, decision parsing, validation.
- `execution/`: simulation + live execution adapter with safety gates.
- `portfolio/`: holdings repository, snapshots, valuation updates.
- `brokers/schwab/`: auth, snapshot, orders, streaming.
- `shared/`: model config, ticker normalization, logging, errors.

This can be achieved gradually without a big-bang rewrite.

## 5. Phased Implementation

### Phase 0 - Baseline and Safety Net
Status: planned

Changes:
- Add snapshot tests for current behavior before refactor.
- Add a fixture-driven test harness for holdings, trade decisions, and market-open/closed states.
- Add deterministic clock abstraction for time-dependent tests.

Acceptance criteria:
- Existing core workflows reproduce current outputs in simulation mode.
- Test harness can run without live Schwab credentials.

Files expected:
- `tests/` additions only.

---

### Phase 1 - Data Isolation and Integrity
Status: planned

Changes:
- Enforce `config_hash` scoping for all holdings/safety/portfolio queries.
- Fix `decider_agent.record_portfolio_snapshot()` to include `config_hash` in read + write paths.
- Add migration checks for `portfolio_history` schema consistency.

Acceptance criteria:
- Two parallel config hashes can run without cross-contamination.
- Snapshot writes succeed on fresh and existing databases.

Hotspot files:
- `decider_agent.py`
- `trading_interface.py`
- `safety_checks.py`
- `dashboard_server.py`
- migration scripts

---

### Phase 2 - Deterministic Orchestrator Context
Status: planned

Changes:
- Remove monkey-patching patterns (for example run-id overrides via function reassignment).
- Introduce explicit `RunContext` object passed from orchestrator to decision/execution calls.
- Standardize run-id generation and propagation.

Acceptance criteria:
- No runtime monkey patching of module functions.
- Run-id and config-hash are explicit inputs, not hidden global state.

Hotspot files:
- `d_ai_trader.py`
- `decider_agent.py`

---

### Phase 3 - Execution Pipeline Unification
Status: planned

Changes:
- Make `TradingInterface` the single live execution entrypoint.
- Keep `decider_agent` focused on decisioning and simulation state intent.
- Ensure safety checks are always in the live path.
- Remove duplicated order execution branches.

Acceptance criteria:
- All live orders flow through one audited pipeline.
- Simulation and live share consistent decision lifecycle states.

Hotspot files:
- `decider_agent.py`
- `trading_interface.py`
- `safety_checks.py`

---

### Phase 4 - Canonical Symbol Normalization
Status: planned

Changes:
- Create one normalization policy module used by decider, sync, and execution.
- Remove conflicting mappings (`GOOG` vs `GOOGL` drift).
- Add unit tests for ticker mapping and round-tripping.

Acceptance criteria:
- Same symbol key is used in holdings, decisions, and broker sync.
- No false "holding not found" from mapping inconsistencies.

Hotspot files:
- `decider_agent.py`
- `trading_interface.py`
- new shared normalization module

---

### Phase 5 - Model and Startup Config Hardening
Status: planned

Changes:
- Centralize model initialization in one startup path.
- Prevent repeated import-time `set_gpt_model` side effects.
- Improve startup warnings to be single-line and actionable.

Acceptance criteria:
- Startup logs are concise and deterministic.
- Model validation behavior is consistent across all entrypoints.

Hotspot files:
- `config.py`
- `main.py`
- `d_ai_trader.py`
- `dashboard_server.py`
- `decider_agent.py`
- `feedback_agent.py`

---

### Phase 6 - Schwab Auth and Token Lifecycle Hardening
Status: planned

Changes:
- Add token health preflight (`access`, `refresh`, and clear reason codes).
- Add explicit handling for refresh 400 cases with guided remediation.
- Add non-sensitive token diagnostics endpoint/CLI helper for local ops.

Acceptance criteria:
- Refresh failures produce clear root-cause messages.
- Operator can recover without reading stack traces.

Hotspot files:
- `schwab_client.py`
- `start_live_trading.sh`
- `verify_schwab_token.py`

---

### Phase 7 - Dead Code and Structural Cleanup
Status: planned

Changes:
- Remove duplicate function definitions and unreachable branches.
- Extract large methods into smaller cohesive units.
- Reduce repeated SQL snippets behind repository helpers.

Acceptance criteria:
- No duplicated critical functions in execution path.
- Lower cyclomatic complexity in decision + execution modules.

Hotspot files:
- `decider_agent.py`
- `main.py`
- `feedback_agent.py`

---

### Phase 8 - Test Coverage and Release Gates
Status: planned

Changes:
- Add assertion-based tests for:
  - config isolation
  - market-open execution guardrails
  - pipeline safety gating
  - ticker normalization
  - Schwab token error handling paths
- Add pre-merge smoke suite.

Acceptance criteria:
- Refactor changes ship behind passing deterministic checks.
- High-risk regressions are caught before runtime.

Hotspot files:
- `tests/`
- CI config

## 6. New Functionality Enabled by Refactor
- Reliable multi-config parallel runs without state bleed.
- One-click "dry run" execution preview with deterministic outcomes.
- Better operator diagnostics for auth/token and live safety decisions.
- Cleaner path to add broker adapters beyond Schwab.
- Faster feature delivery because decisioning and execution are decoupled.

## 7. Suggested Implementation Order
1. Phase 0 and 1 (safety + data correctness)
2. Phase 2 and 3 (orchestration and execution boundary)
3. Phase 4 and 5 (normalization + startup hardening)
4. Phase 6 (auth robustness)
5. Phase 7 and 8 (cleanup + test gates)

## 8. Diff Review Strategy (for our next session)
For each phase:
- Review schema and data scope changes first.
- Review execution-path behavior changes second.
- Review test additions and failure messages last.

This keeps risk visible and deployment-safe.
