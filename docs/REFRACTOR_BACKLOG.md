# Refactor Backlog (Bite-Size)

_Date: 2026-03-15_
_Status: Draft pending CTO split_

## Priority Bands
- **P0**: safety, correctness, decision integrity
- **P1**: modularity and maintainability
- **P2**: UX, reporting polish, optional optimization

## Seed Backlog

### P0
1. Model configuration hardening for GPT-5.4 path (summarizer/decider/feedback)
2. Decision JSON validation and fallback reliability checks
3. Guardrail consistency checks (cash buffer, sizing limits, sell/buy rules)

### P1
4. Extract `decider_agent.py` helper modules for prompt assembly and decision post-processing
5. Extract `feedback_agent.py` API/request and persistence layers
6. Normalize scheduler/orchestrator responsibilities in `d_ai_trader.py`

### P2
7. Dashboard/API response schema cleanup
8. Docs refresh for runtime architecture and env variables

## Notes
- Keep each ticket independently mergeable.
- Include test/verification command in every PR.
- CTO will assign concrete X1/X2 ownership in next split.

## Implemented Today (X2)
- Added `tests/test_decision_shape.py` with schema guardrail coverage for valid `buy`/`sell`/`hold` decisions, missing required field rejection, and invalid action rejection.
- Added `tests/test_decision_validator.py` with edge-case assertions for sell-nonexistent rejection, buy-duplicate rejection, zero-amount rejection, over-cash rejection, and `allow_sell_reuse=False` cash-behavior verification.
- Added `tests/__init__.py` test package marker.

## Implemented Today (X2 Phase 2)
- Added `tests/test_trading_interface.py` with deterministic, fixture-only simulation-mode order flow tests that stub external dependencies and avoid API/database credentials.
- Added `tests/test_dashboard_imports.py` smoke coverage to ensure dashboard decider import bindings (`extract_companies_from_summaries`, `build_momentum_recap`, `fetch_holdings`, `store_momentum_snapshot`, `SUMMARY_MAX_CHARS`) remain valid.
- Kept the new tests intentionally minimal and stable (no network calls, no live Schwab, no DB writes).

## Implemented Today (X2 Phase 3)
- Added `tests/test_ticker_normalize.py` safety-net coverage for `shared.ticker_normalize.normalize_ticker`, including uppercase normalization, rank-prefix stripping, and invalid-input handling.
- Added `tests/test_config_model_overrides.py` with isolated-import stubs to validate startup model override behavior without hitting real DB/OpenAI dependencies.
- Covered model alias resolution (`gpt5.4` → `gpt-5.4`) and `get_agent_model` fallback to default `GPT_MODEL` when overrides are absent.

## Implemented Today (X2 Phase 4)
- Added `tests/test_startup_model_init_cleanup.py` static guardrails that inspect `main.py`, `d_ai_trader.py`, `decider_agent.py`, `feedback_agent.py`, and `dashboard_server.py` for absence of legacy per-module `if _os.environ.get("DAI_GPT_MODEL")` override blocks.
- Extended `tests/test_config_model_overrides.py` to validate centralized `config.py` startup override behavior for `DAI_GPT_MODEL` via shell env and alias normalization (`gpt5.4` → `gpt-5.4`).
- Kept coverage deterministic and lightweight by using import-time stubs only (no network/API/DB).

## Implemented Today (X1 Phase 3)
- Added shared ticker canonicalization helper `shared/ticker_normalize.py` and wired it into `decision_validator._normalize_ticker` plus decider-side `clean_ticker_symbol` to reduce duplicate normalization drift.

## Implemented Today (X1 Phase 4)
- Centralized startup `DAI_GPT_MODEL` application in `config.py` only (import-time env override remains there as the single source of truth).
- Removed duplicate import-time `DAI_GPT_MODEL` override blocks from `main.py`, `d_ai_trader.py`, `decider_agent.py`, `feedback_agent.py`, and `dashboard_server.py`.
- Cleaned up now-unused `set_gpt_model` imports in those modules to eliminate redundant side-effect paths while preserving runtime behavior.

## Implemented Today (Phase 2 — Deterministic RunContext)
- Added `shared/run_context.py` with an immutable `RunContext` dataclass and a `create()` factory.
- Updated `d_ai_trader.py` decider flow to create and pass explicit `RunContext` (`run_id` + `config_hash`) into decider calls.
- Removed runtime monkey-patching of `decider.get_latest_run_id` from orchestrator flow.
- Extended `decider_agent.ask_decision_agent(...)` to accept optional `run_context` while preserving backward compatibility.
- Added fixture/static regression tests:
  - `tests/test_run_context.py`
  - `tests/test_propagation_contract.py`
