---
agent: DeciderAgent
purpose: Trade-by-trade lessons, recurring mistakes, and pattern recognitions
last_updated: 2026-06-25
tags: [memory, decider, trading, risk-management]
graph_status: seed
---

# Decider Agent — Memory

> Append-only knowledge log. Intended for future Obsidian graph view.
> **Conventions:**
> - Each entry starts with an ISO date (`## 2026-05-26`) and 1-3 `#tags`.
> - Use `[[wiki-links]]` to cross-reference tickers, themes, prior entries, or other agents.
> - Keep entries short (3-6 lines). Specific > general. One lesson per entry.
> - Auto-appended by [[feedback_agent]] after each cycle; manually-added entries welcome.

## Lessons Learned
*High-confidence rules earned through P&L.*

## Patterns to Watch
*Setups that historically worked, with the conditions that defined "worked."*

## Mistakes to Avoid
*Tagged by failure mode: `#stop-too-tight`, `#held-too-long`, `#narrative-trap`, `#gap-chase`, `#size-too-big`, etc.*

---

## Log

## 2026-06-18 #synced-inventory #loss-containment
- **Setup:** 20-trade sample was mostly inherited [[Schwab-synced-position]] inventory, not validated alpha entries.
- **Outcome:** Average trade about -0.60%, success rate near 30%; losses in [[NVDA]], [[USO]], [[BA]], [[CME]] outweighed harvested winners.
- **Root cause:** Stale/no-catalyst names were allowed to drift too far before exit.
- **Adjustment:** Treat synced positions as triage inventory; exit weak/no-catalyst losers before -6% to -8% damage.

## 2026-06-20 #catalyst-validity #price-confirmation
- **Setup:** Prior decisions over-weighted impressive headlines and under-weighted whether catalysts were moving price now.
- **Outcome:** [[ROKU]] Fox M&A, [[AAL]] prior momentum, and [[NVDA]] AI/post-earnings narratives failed when tape stayed weak.
- **Root cause:** Catalyst freshness was not tied to VWAP, 10m trend, relative strength, near-high/near-low location, and abnormal volume.
- **Adjustment:** New BUYs require fresh catalyst + sector/index confirmation + technical confirmation above VWAP/opening range.
- **Related:** [[stale-catalyst]], [[headline-risk]], [[price-confirmation]]

## 2026-06-20 #profit-harvesting #capital-rotation
- **Setup:** Winners like [[STLA]], [[SJM]], [[NDAQ]], [[XLE]], and [[AMD]] showed the value of monetizing strength.
- **Outcome:** Harvested winners helped offset weak inherited inventory, but exits must be more systematic.
- **Root cause:** Profitable positions can become narrative traps when +3% to +5% gains are not harvested after momentum fades.
- **Adjustment:** Default SELL full/majority for owned positions ≥+3% unless a fresh ≤1 session catalyst remains price-confirmed.
- **Related:** [[capital-rotation]], [[crowd-fade]], [[realized-profit]]

## 2026-06-20 #ground-truth #anti-hallucination
- **Setup:** Decider outputs must reflect actual holdings, not watchlists, summaries, or prior memory.
- **Outcome:** Invalid HOLD/SELL actions would create execution errors and false portfolio reasoning.
- **Root cause:** Summaries and headlines can mention tickers that are not owned.
- **Adjustment:** Build a holdings set first; SELL/HOLD only if ticker appears in Holdings. Cash-only portfolios may only BUY or give cash_reason.
- **Related:** [[portfolio-state]], [[execution-safety]]

## 2026-06-24 #synced-inventory #quarantine
- **Setup:** Recent cycle again showed listed buy_reasoning dominated by [[Schwab-synced-position]] inventory rather than fresh entries.
- **Outcome:** Success rate near 25% and avg profit about -0.89%; cleanup quality, not entry edge, drove results.
- **Root cause:** Inherited positions were still at risk of being rationalized after the fact with stale narratives.
- **Adjustment:** Quarantine synced holdings at decision start; classify A/B/C using current catalyst, VWAP, 10m trend, relative strength, and volume.
- **Related:** [[inventory-triage]], [[validated-alpha]], [[catalyst-validity]]

## 2026-06-24 #loss-containment #vwap
- **Setup:** Weak holdings with stale catalysts repeatedly performed poorly when below VWAP, near lows, or lacking 10m trend support.
- **Outcome:** Losses became larger than winners when exits waited for deeper confirmation of failure.
- **Root cause:** The process tolerated down >2% positions without demanding fresh reversal evidence.
- **Adjustment:** If owned, down >2%, stale/no catalyst, and weak tape, sell full or at least majority immediately; do not wait for -6% to -8%.
- **Related:** [[NVDA]], [[USO]], [[BA]], [[CME]], [[failed-catalyst]]

## 2026-06-24 #entry-filter #cash-discipline
- **Setup:** Fresh headlines such as legal actions, settlements, recalls, or viral retail moves are tempting but often unconfirmed.
- **Outcome:** Entry expectancy remains unproven, so marginal headline trades should be rejected unless price confirms now.
- **Root cause:** The system historically confused news intensity with tradable catalyst validity.
- **Adjustment:** For new BUYs require fresh catalyst + sector/index or relative strength confirmation + above-VWAP/opening-range technical confirmation.
- **Related:** [[headline-risk]], [[cash-is-a-position]], [[price-confirmation]]

## 2026-06-25 #synced-inventory #early-exit
- **Setup:** Latest feedback again shows inherited [[Schwab-synced-position]] inventory dominated the sample and entry alpha remains unvalidated.
- **Outcome:** Success rate stayed near 25% with average return around -0.89%, meaning exits and risk control must carry expectancy.
- **Root cause:** Weak synced holdings were sometimes defended too long with stale narratives instead of current demand.
- **Adjustment:** For synced positions down >1.0–1.5% with below-VWAP/weak 10m trend or negative sector relative strength, cut full/majority.
- **Related:** [[inventory-triage]], [[loss-containment]], [[vwap]]

## 2026-06-25 #entry-filter #extended-moves
- **Setup:** Headlines like [[MU]] blowout earnings can be fresh but already extended after large visible moves.
- **Outcome:** A fresh catalyst is not automatically a buy when price has pulled from highs or lacks VWAP/10m confirmation.
- **Root cause:** The agent can overpay for obvious consensus stories if it mistakes news quality for asymmetric setup quality.
- **Adjustment:** Buy extended fresh catalysts only if still above VWAP, near highs, volume expanding, and relative strength persists; otherwise cash.
- **Related:** [[gap-chase]], [[headline-risk]], [[price-confirmation]]

## 2026-06-25 #ground-truth #execution-safety
- **Setup:** Portfolio actions must match actual Holdings exactly, even when summaries or memory mention familiar tickers.
- **Outcome:** Invalid HOLD/SELL outputs create execution risk and corrupt performance feedback.
- **Root cause:** Watchlist/news names can be mentally promoted into positions if the holdings set is not built first.
- **Adjustment:** Run final validation: every SELL/HOLD ticker must appear in Holdings; if cash-only, output only BUYs or cash_reason.
- **Related:** [[portfolio-state]], [[anti-hallucination]], [[execution-safety]]

## 2026-06-25 #lot-reconciliation #execution-safety
- **Setup:** Feedback called out repeated symbols and synced lots such as [[NVDA]], [[STLA]], and [[LMT]] needing reconciliation before action.
- **Outcome:** Duplicate or conflicting ticker actions can distort risk reduction and create execution errors.
- **Root cause:** Treating lots as separate theses obscures the net portfolio exposure.
- **Adjustment:** Aggregate duplicate holdings into one net ticker exposure and output only one net action per ticker.
- **Related:** [[portfolio-state]], [[Schwab-synced-position]], [[inventory-triage]]

## 2026-06-25 #missing-data #entry-filter
- **Setup:** Recent headlines included fresh_unconfirmed names such as [[BABA]] and [[BAYRY]], while [[MU]] was fresh but chase-prone after a visible surge.
- **Outcome:** News importance alone does not create edge when live VWAP, 10m trend, volume, and relative strength are absent or deteriorating.
- **Root cause:** The decider can treat missing confirmation as neutral instead of as failed evidence.
- **Adjustment:** Missing catalyst-age, VWAP, trend, volume, or relative-strength data counts as unconfirmed; choose cash over a forced headline buy.
- **Related:** [[headline-risk]], [[price-confirmation]], [[cash-is-a-position]]