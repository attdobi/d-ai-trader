# D-AI-Trader Company Mission Plan (Phase 1)

_Date: 2026-03-15_
_Branch: `mission/phase1-business-plan`_

## Mission
Build an **agent-based trading system** for **daily-to-weekly** trades (not HFT), with strict risk controls and measurable profitability.

## Business Objective (Make Money, Not Noise)
1. Generate positive expected value on a rolling 30-day basis.
2. Protect capital first (drawdown controls and position sizing).
3. Improve decision quality via feedback loops, not constant strategy churn.

## Product Thesis
- Most retail trading systems fail because they overtrade and under-control risk.
- Our edge is **structured cadence + agent specialization + post-trade learning**.
- We focus on higher-conviction opportunities over 1–5 trading days, not scalp speed.

## Operating Model (Org)
- **Pista (CEO):** execution, planning, prioritization, release gating
- **TheoMaximus (CTO):** architecture, decomposition, review gate
- **X1 (Engineer-Core):** backend/refactor/core trading logic/data contracts
- **X2 (Engineer-Integration):** dashboard/API integration/docs/testing/observability

## What Success Looks Like (KPIs)
### Trading KPIs
- Win rate (target: > 52% over 30 trading days)
- Profit factor (target: > 1.2)
- Max drawdown (target: < 8%)
- Avg hold duration aligned with strategy (1–5 days)
- Overtrading control (daily trade cap respected 100%)

### System KPIs
- Zero critical runtime regressions in market hours
- Every release behind feature flags or safe defaults
- Clear decision audit trail per cycle (summary → decision → validation → execution)
- Mean time to diagnose failed cycle < 15 min

## Phase Plan (2 Weeks)

### Week 1 — Stabilize + Modularize Foundations
- Lock architecture boundaries around core flows:
  - summarization
  - decisioning
  - execution/validation
  - feedback/learning
- Start bite-size refactors in highest-risk monoliths (`decider_agent.py`, `feedback_agent.py`, `main.py`, `d_ai_trader.py`, `config.py`).
- Introduce/standardize per-agent model configuration path to support GPT-5.4 rollout safely.

### Week 2 — Harden + Measure
- Add targeted regression checks for decision JSON validity and guardrail behavior.
- Improve observability for trade cycle attribution and model response quality.
- Validate daily-to-weekly strategy tuning with simulation logs before any live expansion.

## GPT-5.4 Direction (Summarizer, Decider, Feedback)
We will transition to GPT-5.4 in incremental, low-risk slices:
1. Expand model registry/config to accept GPT-5.4 variants.
2. Add per-agent model selection path (summarizer/decider/feedback).
3. Keep fallback model support for decider safety.
4. Roll out in simulation first with decision quality logging.

## Refactor Principles
1. No big-bang rewrites.
2. One small shippable change per ticket.
3. Every change updates docs + changelog note.
4. Prefer extraction over mutation in monolith files.
5. Keep runtime behavior unchanged unless explicitly planned.

## Immediate Next Actions
1. CTO publishes split backlog for X1/X2 with acceptance criteria.
2. X1 and X2 start first incremental refactor tickets.
3. Track all changes on feature branches and merge via PR after review.

## Open Item
There is mention of an existing refactor-suggestions file; if not located in repo root/docs, we need its exact path so it can be folded into backlog priority.

## Implemented Today
- Added `gpt-5.4` (plus alias `gpt5.4`) to model selection in `config.py`.
- Added per-agent model overrides via env vars: `DAI_MODEL_SUMMARIZER`, `DAI_MODEL_DECIDER`, `DAI_MODEL_FEEDBACK`.
- Added `get_agent_model(agent_name)` and wired `PromptManager.ask_openai()` to use per-agent overrides by default, while preserving existing behavior when overrides are unset.
