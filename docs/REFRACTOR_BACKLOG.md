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
