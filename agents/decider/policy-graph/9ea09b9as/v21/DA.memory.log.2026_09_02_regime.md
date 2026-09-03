---
id: DA.memory.log.2026_09_02_regime
version: DeciderAgent.9ea09b9as.v21
agent: DeciderAgent
title: "2026-09-02 #regime #extension-chase #reentry #kill-geometry"
node_type: entry
polarity: gate
polarity_source: heuristic
parent: DA.memory.log
field: memory
order: 13
owner: db
status: active
compiled: stored
locked: false
provenance: prompt_versions#599
sep_before: ""
sep_after: "\n\n"
body_sha256: 823e417279e9d460d5e9a66eb218e23dcb982cd0f49bddf05d15e3841163a8f6
tags: [regime, extension-chase, reentry, kill-geometry]
tickers: [IONQ, MDB, MRVL, ORCL, RKLB]
---
## 2026-09-02 #regime #extension-chase #reentry #kill-geometry
- **Setup:** Aug 5–14 the "controlled pullback in a strong monthly trend" playbook ran 65–73% win / +$339 while SPY/QQQ and the momentum leaders were above their 20d MAs. Aug 17 – Sep 2 the SAME rules ran 22–33% win / −$275: every extension bucket lost, the 6–10%-above-20d bucket went 0-for-5.
- **Outcome:** [[IONQ]] −10.4% (entered +15% above 20d), [[RKLB]] −7.2% (+9.4%), [[MRVL]] −9.1% (+9.0%), [[ORCL]] −5.0%/−3.9%/−3.2% (three re-entries in 8 days), [[MDB]] −15.2% (earnings gap through an unpriced "20d break" kill).
- **Root cause:** (1) the screener capped only the DAY move, so "pullbacks" 9–18% above the 20d MA were served as front-run candidates; (2) the only kill was "exit on 20d break" — 9–15% away; (3) same-ticker re-entry within 3 days of an exit (18 trades, −$156) was the largest single leak; (4) no regime read — the prompt said cash is failure, so the book stayed deployed into a momentum unwind.
- **Adjustment:** INDEX REGIME gate; extension cap ≤5% full / 5–8% half (RISK-ON only) / >8% reject; `K:<price>;D:<%>` from supplied numbers, ≤3% or half size, ≤6% or pass; 2-session re-entry quarantine (screener drops exited names); max 2 correlated semis/AI/quantum names.
- **Related:** [[front-run-not-chase]] [[feedback_agent]] [[reentry-quarantine]]