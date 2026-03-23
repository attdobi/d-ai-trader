# New Functionality Roadmap (Post-Refactor)

This roadmap lists features that become practical once the refactor phases are in place.

## F1. Deterministic Dry-Run API
Depends on: Phase 2, Phase 3

Description:
- Expose a review endpoint that returns decision parsing, validation outcomes, safety gating, and expected state deltas without placing live orders.

Value:
- Safer operator review before market-open automation.

## F2. Multi-Config Portfolio Guardrails
Depends on: Phase 1

Description:
- Enforce strategy-level and account-level risk checks with clean config-hash boundaries.

Value:
- Enables parallel strategy experiments with fewer isolation failures.

## F3. Token Health and Recovery Assistant
Depends on: Phase 6

Description:
- Add CLI and dashboard diagnostics for token status, refresh readiness, and exact remediation steps.

Value:
- Shorter downtime when broker auth drifts.

## F4. Symbol Consistency Explorer
Depends on: Phase 4

Description:
- Diagnostic view showing source symbol, normalized symbol, holdings symbol, and broker symbol.

Value:
- Faster root cause analysis for missed sells/buys due to symbol mismatch.

## F5. Structured Run Audit Export
Depends on: Phase 3, Phase 5, Phase 8

Description:
- Export per-run JSON audit packages: summaries used, prompt metadata, decisions, validations, safety blocks, and execution results.

Value:
- Better explainability and easier post-mortems.
