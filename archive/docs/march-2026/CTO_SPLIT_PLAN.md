# CTO Split Plan — X1 / X2 Execution

_Date: 2026-03-15_
_Status: Active — Week 1 starts now_
_Owner: TheoMaximus (Tech Lead)_

---

## 1. Two-Week Execution Plan

### Week 1 — Stabilize Foundations (Mar 17–21)

| Day | Business Goal | Technical Work |
|-----|--------------|----------------|
| Mon | Establish safe model config path for GPT-5.4 | **X1:** Add GPT-5.4 to `set_gpt_model()` valid list + per-agent model registry in `config.py`. **X2:** Add snapshot tests for current decision JSON output shape. |
| Tue | Ensure decision integrity under parallel configs | **X1:** Enforce `config_hash` scoping in `decider_agent.py` portfolio snapshot read/write. **X2:** Add assertion tests for `DecisionValidator` edge cases. |
| Wed | Reduce monolith risk in decider | **X1:** Extract prompt assembly helpers from `decider_agent.py` into `decisioning/prompt_builder.py`. **X2:** Verify extraction doesn't break dashboard imports (integration smoke test). |
| Thu | Harden execution boundary | **X1:** Audit `execute_real_world_trade()` vs `TradingInterface.execute_trade_decisions()` — document overlap, remove dead branch if safe. **X2:** Add test for `TradingInterface` sim-mode order flow. |
| Fri | Buffer / review / catch-up | Both: PR reviews, fix any regressions from Mon–Thu, update docs. |

### Week 2 — Harden + Measure (Mar 24–28)

| Day | Business Goal | Technical Work |
|-----|--------------|----------------|
| Mon | Normalize symbols across modules | **X1:** Create `shared/ticker_normalize.py` — single canonical mapping used by decider, trading_interface, schwab_client. **X2:** Add unit tests for ticker round-trip (GOOG↔GOOGL etc.). |
| Tue | Startup config hardening | **X1:** Centralize `set_gpt_model` calls — remove repeated import-time side effects in `main.py`, `d_ai_trader.py`, `dashboard_server.py`, `decider_agent.py`, `feedback_agent.py`. **X2:** Verify startup log output is deterministic (no duplicate model announcements). |
| Wed | GPT-5.4 simulation rollout | **X1:** Wire per-agent model selection so summarizer/decider/feedback can each specify model independently. **X2:** Run simulation cycle with GPT-5.4 on decider agent only; log decision quality diff vs GPT-5.2. |
| Thu | Observability for trade cycles | **X1:** Add run-level correlation ID propagation from orchestrator to decider to execution. **X2:** Add dashboard panel or log view showing per-run decision audit trail. |
| Fri | Release gate + retrospective | Both: Pre-merge smoke suite green. Document what shipped. Retrospective on blockers. |

---

## 2. Prioritized Bite-Size Backlog

### P0 — Safety, Correctness, Decision Integrity

| # | Task | Owner | Size | Files |
|---|------|-------|------|-------|
| 1 | Add GPT-5.4 to valid model list + per-agent model config registry | X1 | S | `config.py` |
| 2 | Enforce `config_hash` in portfolio snapshot read/write paths | X1 | M | `decider_agent.py`, `trading_interface.py` |
| 3 | Add decision JSON shape snapshot tests | X2 | S | `tests/test_decision_shape.py` (new) |
| 4 | Add `DecisionValidator` edge-case assertions (sell-nonexistent, buy-duplicate, zero-amount) | X2 | S | `tests/test_decision_validator.py` (new) |
| 5 | Audit + remove duplicate execution path (`execute_real_world_trade` vs `TradingInterface`) | X1 | M | `decider_agent.py`, `trading_interface.py` |
| 6 | Guardrail consistency check: verify cash buffer + sizing limits match between `safety_checks.py` and `decider_agent.py` constants | X2 | S | `safety_checks.py`, `decider_agent.py` |

### P1 — Modularity and Maintainability

| # | Task | Owner | Size | Files |
|---|------|-------|------|-------|
| 7 | Extract prompt assembly from `decider_agent.py` into `decisioning/prompt_builder.py` | X1 | M | `decider_agent.py` → new module |
| 8 | Extract feedback API/request layer from `feedback_agent.py` into `feedback/api_client.py` | X1 | M | `feedback_agent.py` → new module |
| 9 | Create `shared/ticker_normalize.py` — one canonical symbol policy | X1 | S | new module, then update imports |
| 10 | Centralize `set_gpt_model` — remove repeated import-time calls across 5 files | X1 | S | `main.py`, `d_ai_trader.py`, `dashboard_server.py`, `decider_agent.py`, `feedback_agent.py` |
| 11 | Normalize orchestrator scheduling in `d_ai_trader.py` (explicit RunContext) | X1 | M | `d_ai_trader.py`, `decider_agent.py` |
| 12 | Wire per-agent model selection for summarizer/decider/feedback | X1 | M | `config.py`, `decider_agent.py`, `feedback_agent.py`, `main.py` |
| 13 | Add `TradingInterface` sim-mode integration test | X2 | S | `tests/test_trading_interface.py` (new) |
| 14 | Verify dashboard imports survive decider extraction (smoke test) | X2 | S | `tests/test_dashboard_imports.py` (new) |
| 15 | Run GPT-5.4 simulation cycle on decider + log decision quality comparison | X2 | M | simulation logs, `d_ai_trader.py` |

### P2 — UX, Reporting, Polish

| # | Task | Owner | Size | Files |
|---|------|-------|------|-------|
| 16 | Dashboard API response schema cleanup (consistent JSON shapes) | X2 | M | `dashboard_server.py` |
| 17 | Add run-level correlation ID from orchestrator → decider → execution | X1 | M | `d_ai_trader.py`, `decider_agent.py`, `trading_interface.py` |
| 18 | Per-run decision audit trail in dashboard | X2 | M | `dashboard_server.py`, `templates/` |
| 19 | Docs refresh: runtime architecture, env variables, model config | X2 | S | `README.md`, `docs/` |
| 20 | Pre-merge smoke suite (CI-ready test harness) | X2 | M | `tests/`, CI config |

---

## 3. First 4 Executable Tickets

### Ticket X1-001: Add GPT-5.4 to model registry + per-agent model config

**Owner:** X1 (backend/infra)
**Priority:** P0
**Size:** S (< 100 lines changed)

**Description:**
Expand the model allowlist in `config.py` to accept `gpt-5.4` (and alias `gpt5.4`). Add a `AGENT_MODEL_OVERRIDES` dict that allows per-agent model selection (keys: `summarizer`, `decider`, `feedback`; values: model name or `None` for default). Add a `get_agent_model(agent_name)` helper that returns the override or falls back to `GPT_MODEL`.

**Acceptance Criteria:**
- [ ] `set_gpt_model("gpt-5.4")` succeeds and sets `GPT_MODEL` correctly
- [ ] `set_gpt_model("gpt5.4")` resolves via alias
- [ ] `AGENT_MODEL_OVERRIDES` is populated from env vars: `DAI_MODEL_SUMMARIZER`, `DAI_MODEL_DECIDER`, `DAI_MODEL_FEEDBACK`
- [ ] `get_agent_model("decider")` returns the override when set, else `GPT_MODEL`
- [ ] Existing behavior unchanged when no overrides are set (backward compatible)
- [ ] No import-time side effects added

**Files:**
- `config.py` (modify `set_gpt_model`, add `AGENT_MODEL_OVERRIDES`, add `get_agent_model`)

**Risk:** Low. Additive change. No execution path changes. Gated behind env var opt-in.

---

### Ticket X1-002: Enforce config_hash scoping in decider portfolio snapshots

**Owner:** X1 (backend/infra)
**Priority:** P0
**Size:** M (~150 lines changed)

**Description:**
Audit all SQL queries in `decider_agent.py` that read or write `portfolio_history` / holdings data. Ensure every query includes `config_hash` in its `WHERE` clause (reads) and `INSERT` values (writes). The `record_portfolio_snapshot()` and `fetch_holdings()` functions are the primary targets. Also check `build_momentum_recap()`.

**Acceptance Criteria:**
- [ ] `record_portfolio_snapshot()` writes include `config_hash` column
- [ ] `fetch_holdings()` filters by `config_hash`
- [ ] `build_momentum_recap()` filters by `config_hash`
- [ ] Two parallel configs (different `config_hash`) produce isolated portfolio histories when run against same DB
- [ ] No changes to `trading_interface.py` or `safety_checks.py` in this ticket (those come later)

**Files:**
- `decider_agent.py` — `record_portfolio_snapshot()`, `fetch_holdings()`, `build_momentum_recap()`

**Risk:** Medium. Touching SQL in the decision path. Must verify with existing simulation data that no queries silently return empty after scoping is added. Mitigation: run a simulation cycle before and after, diff the decision outputs.

---

### Ticket X2-001: Decision JSON shape snapshot tests

**Owner:** X2 (UI/integration/tests)
**Priority:** P0
**Size:** S (< 80 lines new)

**Description:**
Create a test module that validates the expected shape of decision JSON output from the decider agent. Use fixture data (not live API calls). Assert required keys (`action`, `ticker`, `amount_usd`, `reason`), valid action values (`buy`, `sell`, `hold`), and type constraints. This forms the regression baseline before any refactoring touches the decider.

**Acceptance Criteria:**
- [ ] Test file at `tests/test_decision_shape.py`
- [ ] At least 5 test cases: valid buy, valid sell, valid hold, missing field rejection, invalid action rejection
- [ ] Tests use fixture data only (no OpenAI calls, no DB)
- [ ] Tests pass with `pytest tests/test_decision_shape.py` from repo root
- [ ] Documents the canonical decision schema in test docstring

**Files:**
- `tests/test_decision_shape.py` (new)
- `tests/__init__.py` (new, empty)

**Risk:** Low. Pure additive. No runtime code changes. Establishes the safety net for future refactoring.

---

### Ticket X2-002: DecisionValidator edge-case assertion tests

**Owner:** X2 (UI/integration/tests)
**Priority:** P0
**Size:** S (< 100 lines new)

**Description:**
Write targeted tests for `DecisionValidator` (`decision_validator.py`) covering edge cases that matter for real-money safety: selling a ticker not in holdings, buying a ticker already held, zero/negative amounts, amounts exceeding available cash, and the `allow_sell_reuse` flag behavior.

**Acceptance Criteria:**
- [ ] Test file at `tests/test_decision_validator.py`
- [ ] Cases covered: sell-nonexistent-ticker → rejected; buy-already-held → rejected; amount=0 → rejected; amount > cash → rejected; sell-reuse disabled prevents cash increase for subsequent buys
- [ ] Tests use fixture data only (mock holdings list + cash float)
- [ ] Tests pass with `pytest tests/test_decision_validator.py` from repo root
- [ ] Each test has a clear assertion message explaining the guardrail being tested

**Files:**
- `tests/test_decision_validator.py` (new)
- `decision_validator.py` (read-only reference, no modifications)

**Risk:** Low. Pure additive. Tests the existing validator without modifying it. Any failures indicate real gaps in the validator that should be flagged for P0 follow-up.

---

## 4. Existing Refactor Suggestions — Where They Are and How They Were Used

### File Locations

| File | Path | Contents |
|------|------|----------|
| Refactor Plan | `d-ai-trader-refactor/refactor-plan.md` | 8-phase implementation plan with acceptance criteria per phase |
| Change Matrix | `d-ai-trader-refactor/change-matrix.md` | Risk → change → benefit mapping with P0/P1/P2 priorities |
| New Functionality Roadmap | `d-ai-trader-refactor/new-functionality-roadmap.md` | 5 features unlocked by the refactor (dry-run API, multi-config guardrails, token health, symbol explorer, audit export) |
| Refactor README | `d-ai-trader-refactor/README.md` | Review guide for the above artifacts |
| Refactor Backlog (seed) | `docs/REFRACTOR_BACKLOG.md` | Seed backlog with P0/P1/P2 bands, pending CTO split |
| Company Mission Plan | `docs/COMPANY_MISSION_PLAN.md` | 2-week phase plan, KPIs, org model, GPT-5.4 direction |

### How They Were Used

The existing refactor artifacts were the primary input for this split plan:

1. **Priority mapping:** The `change-matrix.md` P0 items (data isolation, execution boundary, portfolio snapshot integrity) directly became our P0 backlog tickets (#1–6).
2. **Phase sequencing:** The `refactor-plan.md` Phase 0–1 (safety net + data isolation) mapped to Week 1, and Phases 2–5 (orchestration, execution, normalization, startup) mapped to Week 2.
3. **Ownership assignment:** Backend-heavy phases (data scoping, execution unification, model config) went to X1. Test/integration/dashboard work went to X2.
4. **Ticket sizing:** The refactor plan's monolithic phases were broken into independently shippable tickets. For example, Phase 5 ("Model and Startup Config Hardening") became two tickets: #1 (model registry, X1) and #10 (centralize set_gpt_model calls, X1).
5. **New functionality roadmap** items (F1–F5) were deferred to post-Week 2 but informed the correlation ID and audit trail tickets (#17, #18) as stepping stones.
6. **Backlog seed** (`REFRACTOR_BACKLOG.md`) items were expanded with concrete acceptance criteria and file references rather than used as-is.

---

## 5. GPT-5.4 Rollout Recommendation — Summarizer, Decider, Feedback Agents

### Recommendation: Incremental, Per-Agent, Simulation-First

GPT-5.4 should be rolled out to the three core AI agents (summarizer, decider, feedback) in a controlled, staged manner. **Do not switch all agents simultaneously.**

### Rollout Sequence

| Phase | Agent | Timeline | Gate |
|-------|-------|----------|------|
| **Phase A** | Decider only | Week 2, Day 3 (Wed) | Per-agent model config is merged (Ticket X1-001) |
| **Phase B** | Feedback | Week 2+1 | Phase A shows no regression in decision JSON validity |
| **Phase C** | Summarizer | Week 3 | Phases A+B stable for 3+ simulation days |

### Why This Order

1. **Decider first** — highest value, most structured output (JSON decisions). Easy to validate: does the output parse? Are the decisions reasonable? Direct comparison with GPT-5.2 decision logs.
2. **Feedback second** — less risk, more tolerance for prose variation. Feedback quality is assessed over days/weeks, not per-cycle.
3. **Summarizer last** — summarizer output feeds into the decider. Changing both simultaneously makes it impossible to attribute regressions. Keep the summarizer on GPT-5.2 while validating GPT-5.4 decider behavior.

### Implementation Details

1. **Config path (Ticket X1-001):** Add `DAI_MODEL_DECIDER`, `DAI_MODEL_SUMMARIZER`, `DAI_MODEL_FEEDBACK` env vars. Each agent calls `get_agent_model("decider")` instead of reading `GPT_MODEL` directly.
2. **Fallback:** If a GPT-5.4 API call fails with a model-not-found or capacity error, fall back to `GPT_MODEL` (currently GPT-5.2) and log a warning. Never silently degrade.
3. **Quality logging:** During Phase A, log both the raw decision JSON and a quality score (valid JSON? all required fields? reasonable amounts?) for every GPT-5.4 cycle. Compare against the GPT-5.2 baseline from the snapshot tests (Ticket X2-001).
4. **Kill switch:** `DAI_MODEL_DECIDER=""` (empty) reverts to default. No code change needed to roll back.
5. **Simulation first:** GPT-5.4 runs in simulation mode for at least 2 full trading days before any live consideration. Live rollout requires explicit CEO approval.

### Risks

- **Prompt sensitivity:** GPT-5.4 may interpret the aggressive decider system prompt differently. The existing prompt is tuned for GPT-5.1/5.2 behavior. Monitor for changes in sell aggressiveness and position sizing.
- **Token usage:** GPT-5.4 may use more reasoning tokens. Monitor cost per cycle.
- **Rate limits:** New model may have different rate limit tiers. Test in simulation first.

### Success Criteria for Live Promotion

- [ ] 2+ simulation days with zero invalid decision JSONs
- [ ] Decision quality parity or improvement vs GPT-5.2 (win rate, profit factor on simulated trades)
- [ ] No increase in "hallucinated ticker" or "sell-nonexistent" validator rejections
- [ ] Cost per cycle within 2x of GPT-5.2 baseline
- [ ] CEO sign-off

---

## Appendix: File Complexity Reference

| File | Lines | Role | Refactor Priority |
|------|-------|------|-------------------|
| `decider_agent.py` | 2,998 | Decision logic, prompt assembly, portfolio snapshots, trade execution | P0 — largest monolith, highest risk |
| `dashboard_server.py` | 2,366 | Flask dashboard, API endpoints, manual triggers | P2 — large but lower risk |
| `feedback_agent.py` | 1,625 | Trade outcome tracking, feedback loops, API calls | P1 — medium monolith |
| `schwab_client.py` | 1,263 | Broker API auth, orders, account data | P1 — isolated, lower coupling |
| `config.py` | 917 | Global config, model management, DB engine | P0 — touched by everything |
| `trading_interface.py` | 902 | Execution abstraction (sim + live) | P0 — execution boundary |
| `main.py` | 900 | Summarizer (Selenium scraping, screenshots) | P1 — self-contained |
| `d_ai_trader.py` | 890 | Orchestrator (scheduling, agent coordination) | P1 — RunContext needed |
| `safety_checks.py` | 371 | Risk limits and guardrails | P0 — must stay correct |
| `decision_validator.py` | 198 | JSON validation for trade decisions | P0 — critical safety net |
