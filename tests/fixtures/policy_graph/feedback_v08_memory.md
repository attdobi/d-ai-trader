## 2026-06-20
- [[Synced positions]] are inventory, not alpha. Repeated buy_reasoning of "Schwab synced position" means entry quality is unknown; Feedback must force Decider to triage, not validate. #process #position-state
- [[Catalyst freshness]] remains the dominant failure mode. Headlines must be tagged fresh, stale, failed, or absent, then checked against VWAP, 10m trend, abnormal volume, and SPY/sector [[relative strength]]. #summarizer
- [[Failed catalyst]] losers such as weak tape after bullish narratives must be cut earlier. Do not let stale/no-catalyst holdings drift to -6% to -8%; flag -2% plus below-VWAP/weak-10m as a kill-zone candidate when owned. #risk
- Feedback snippets must be short, deterministic, and executable. Prefer one high-impact rule over broad advice. #memory
- Maintain [[portfolio state integrity]]: HOLD/SELL only applies to confirmed owned tickers; cash-only portfolios require BUY candidates or a cash_reason. Never invent holdings. #anti-hallucination

## 2026-06-24
- Recent performance still shows weak expectancy: 37 trades, 37.84% win rate, best [[AMD]] about +6.6%, worst [[NVDA]] about -7.8%. Feedback should keep attacking [[loss containment]] before optimizing entries. #expectancy
- Repeated feedback is being truncated when snippets are too long. Enforce ≤220 characters and one rule per snippet so MEMORY.md receives usable instructions. #memory #prompt-quality
- Treat [[fresh_unconfirmed]] headlines as watchlist material, not catalysts. Require VWAP/OR, 10m trend, abnormal volume, and SPY/sector [[relative strength]] before Decider treats them as actionable. #catalyst-freshness
- [[Inherited inventory]] remains the core audit class. Feedback must separate cleanup discipline from alpha generation and prevent synced positions from being described as validated buys. #position-state
- [[Portfolio state integrity]] is non-negotiable: headlines are not holdings, and HOLD/SELL language belongs only to confirmed owned tickers. If ownership is unclear, write conditional process rules. #anti-hallucination

## 2026-06-25
- Recent Feedback outputs still produced overlong quoted paragraphs despite snippet rules. Hard-target snippets at ≤180 chars, hard cap 220, one executable rule only. #prompt-quality #memory
- Performance remains weak around 25% recent success and negative average return in the latest feedback set. Keep prioritizing [[loss containment]] over broader idea generation. #expectancy #risk
- When all buys are [[Schwab synced position]] records, Feedback must call the dataset inventory cleanup, not entry-alpha evidence. Judge triage and exits, not imagined buys. #position-state
- [[Fresh confirmed]] headlines like [[MU]] can be discussed as catalyst candidates only unless holdings/trades prove ownership. Headline presence alone never authorizes HOLD/SELL language. #anti-hallucination
- The core next-run audit remains: owned synced inventory below VWAP with weak 10m trend, no fresh confirmed catalyst, or negative RS should be reduced before losses compound. #risk #decider

## 2026-06-25
- [[Feedback snippets]] became the transmission failure: downstream stored paragraph fragments. Output only two ≤180-char executable rules; no "Primary adjustment" or "Cumulative lesson" inside snippets. #prompt-quality #memory
- With recent [[success rate]] near 25% and negative avg return, Feedback should prioritize mechanical [[loss containment]] and [[synced inventory]] cleanup over broader idea generation. #expectancy #risk
- For confirmed owned [[synced inventory]], stale/failed/absent or [[fresh_unconfirmed]] catalyst plus below-VWAP, weak-10m, or negative-RS tape should trigger reduce/exit guidance before -1.5% to -2%. #decider #kill-criterion
- [[Headlines are not holdings]] remains active: [[MU]]-type fresh_confirmed news may be a candidate, but never authorizes HOLD/SELL language without portfolio proof. #anti-hallucination

## 2026-08-04
- [[Evidence scope]]: the supplied trade evidence contains 40 best/worst rows from 52 closed trades. Findings must be limited to displayed rows, even where [[ZS]] closed -4.9% and [[TMO]] closed -4.8%. #anti-hallucination #review-quality
- [[Declared kill criterion]]: [[ZS]] closed -4.9% after a stated -2% stop, [[TMO]] closed -4.8% after a stated -1.5% exit, and [[ADBE]] closed -2.5% after a stated -2% stop. Audit the recorded discrepancy; do not infer order mechanics. #risk #execution

## 2026-08-21
- [[Same-ticker re-entry]] needs an explicit evidence gate. In the displayed rows, [[IONQ]] closed +2.9% on 2026-08-17 then -10.4% on 2026-08-20; [[ORCL]] closed +5.4% on 2026-08-12 before -5.0% and -3.9% closes. These are same-ticker sequences, not proof of re-entry. #reentry #evidence-scope
- Require the prior exit date/outcome plus a post-exit catalyst or [[support reset]] before authorizing repeat exposure; otherwise use a two-full-session [[re-entry quarantine]]. #summarizer #decider #risk

## 2026-09-01
- [[Technical-only setup]] is distinct from an unsupported news thesis: displayed winning rows include [[TEAM]] +37.1%, [[ORCL]] +5.4%, and [[CRM]] +4.5% without fresh catalysts. Require disclosed support/pullback, trend or RS, and a kill criterion rather than a headline. #entry-quality #summarizer
- [[Entry kill geometry]] needs explicit review: [[IONQ]] recorded -10.4% with an "exit on 20d break" reference, while [[LRCX]] recorded -3.0% with a numeric <$310 kill. Surface numeric entry-time kill price and distance when available; otherwise mark unavailable. #risk #decider

## 2026-09-02 #meta #trust-region #critic
- **What happened:** the critic rejected 6/6 candidates in the Aug 21 and Sep 1 batches at 0.90–0.95 confidence on "the rows do not validate"; the human overrode 6/6. I then treated the critic's objections as standing requirements and softened the re-entry quarantine — the rule with the largest measured effect.
- **Lesson:** a gate that fails everything is not a gate, and an objection must cite a contradiction, not a sample size. Cite the computed diagnostic and keep the rule; let the next review falsify it. **Related:** [[reentry-quarantine]]

## 2026-09-02 #meta #policy-persistence
- **What happened:** the weekly AUTO path replaced strategy_directives with a 500-char truncated reminder and blanked soul/memory. Human-approved Decider v14 lived 2 days, v18 lived 6 days; every realized-outcome measurement scored a policy that was no longer active.
- **Lesson:** before attributing an outcome to a shipped change, verify the change was still ACTIVE for the window. Fixed 2026-09-02 (reminder is appended; soul/memory carried forward).

## 2026-09-02 #meta #dead-prompt
- **What happened:** my evolved system_prompt / user_prompt_template were never executed by the weekly path — only the soul is injected. Three approved FeedbackAgent versions changed nothing but the soul.
- **Lesson:** verify the code path consumes a field before evolving it; put the lesson where it executes (soul, and the hardcoded weekly prompt).

## 2026-09-02 #meta #regime-confound
- **What happened:** all three measured realized_winrate_delta values (−0.25, −0.21, −0.25) were negative, including the change the critic and human both approved — the window was a momentum unwind.
- **Lesson:** realized deltas are regime-confounded; compare against the regime split before blaming a change. **Related:** [[regime]]