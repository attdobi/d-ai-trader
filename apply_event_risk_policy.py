#!/usr/bin/env python
"""Apply the 2026-09-14 event-risk policy change through the policy graph (one-off, idempotent).

Audit that day: the Summarizers flagged the Sep 16 FOMC decision in 8 of 36 summaries — in the very
paragraph the Decider reads — and 0 of the previous 96 Decider outputs mentioned the Fed, a macro print
or an earnings date. Three attributable changes close the gap (the code side — `event_calendar.py`,
the EVENT CALENDAR block, the diagnostics — ships with the same commit):

  1. DeciderAgent proposal, 3 guideline files: add `9. EVENT GATE` under DA.directives.strategy
     (primary), add a Risk-Management soul bullet (edit DA.soul.risk_management), add lesson
     `#event-risk` under DA.memory.lessons — prompt + SOUL + MEMORY together, as every Decider change.
  2. FeedbackAgent proposal, 2 files: edit FA.soul.review_style (primary — the weekly path executes
     the soul) and add `10. EVENT RISK` under FA.directives.audit_order (manual path / record).
  3. SummarizerAgent v<N+1> as a plain version row: the system / user templates are locked for
     proposals, so the EVENT RISK wording (Fed/FOMC, CPI/jobs, earnings, geopolitical shocks, with
     dates) is edited directly, together with the decider_uses directive, the soul and the memory.

Each proposal runs the same validation + round-trip check as a drafted one, gets the real critic
verdict recorded in prompt_change_reviews, and is then applied by the operator whatever the verdict
(the change was requested by the operator; the verdict stays on the record, actor recorded).

    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_event_risk_policy.py --dry-run
    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_event_risk_policy.py [--skip-critic]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ACTOR = "claude_code (operator: Attila Dobi, 2026-09-14)"
CREATED_BY = "claude_code"

# ----------------------------------------------------------------------------- Decider texts
DECIDER_GATE = (
    "9. EVENT GATE — read the EVENT CALENDAR block right after the INDEX REGIME line, every cycle; it never relaxes an "
    "earlier gate, and a missing block = fall through. MACRO WINDOW (FOMC decision within the next 2 sessions or today "
    "before 2:00 pm ET; CPI or jobs report next session) = no full-size BUY: at most 1 half-size BUY with D ≤2%, and "
    "every BUY/HOLD reason names the event and its date. EARNINGS: a candidate that reports inside the next 5 sessions = "
    "REJECT (state \"earnings <date> inside hold window\"); a holding that reports within 2 sessions = SELL before the "
    "print, or TRIM to half only if RISK-ON and ≥ +3%. No window = fall through. Falsified if 20 in-window half-size "
    "entries taken under this gate average better than the 20 nearest out-of-window entries."
)
DECIDER_SOUL_ANCHOR = "- **Correlation is one position.**"
DECIDER_SOUL_BULLET = (
    "- **A scheduled binary event is a gap, not noise.** An FOMC decision, a CPI/jobs print or an earnings date inside "
    "the 1–5 day hold gaps through any kill — the kill protects against drift, not a gap. Read the EVENT CALENDAR block "
    "with the regime: no full-size entry inside a macro window (FOMC within 2 sessions, CPI/jobs next session), no entry "
    "in a name that reports inside the hold window, and sell or trim what reports within 2 sessions. (Paid for by "
    "[[MDB]] −15.2% on 2026-09-02, an earnings gap through a 20d-break kill.)"
)
DECIDER_LESSON = (
    "- **#event-risk — Scheduled binary events gap through kills.** Read the EVENT CALENDAR block every cycle. FOMC "
    "within 2 sessions (or today before 2 pm ET) or a CPI/jobs print next session = at most 1 half-size BUY with D ≤2%, "
    "the event named in the reason; a candidate reporting inside 5 sessions = reject; a holding reporting within 2 "
    "sessions = sell/trim before the print. (Paid for by [[MDB]] −15.2% earnings gap, 2026-09-02. Audit 2026-09-14: the "
    "Summarizers flagged the Sep 16 FOMC in 8 of 36 summaries; 0 of 96 decisions in 30 days acknowledged any scheduled "
    "event.)"
)
DECIDER_REASONING = (
    "Scheduled binary events were produced by the Summarizers and discarded by the Decider: on 2026-09-14 the Sep 16 "
    "FOMC decision was named in 8 of 36 summaries while 0 of 96 decisions in 30 days acknowledged any scheduled event; "
    "the regime gate is purely technical, the prompt carried no date and no earnings dates, and the largest single loss "
    "of the window (MDB −15.2%, 2026-09-02) was an earnings gap through an unpriced kill. The code now supplies an EVENT "
    "CALENDAR block (today's date, sessions to FOMC / CPI / jobs, earnings dates of holdings and watchlist names); this "
    "gate is the rule that consumes it, with the soul and a lesson carrying the same thresholds."
)

# ----------------------------------------------------------------------------- Feedback texts
FA_SOUL_EDITS = [
    ("Then regime, geometry, re-entry, payoff. Then rules.",
     "Then regime, geometry, re-entry, payoff, event windows. Then rules."),
    ("correlated books, synced inventory, phantom holdings.",
     "correlated books, synced inventory, phantom holdings, entries inside a macro window (FOMC within 2 sessions, "
     "CPI/jobs next session) or in a name that reports inside the hold, holds through a scheduled print, and dated "
     "events the Summarizers named that the Decider never acknowledged."),
]
FA_AUDIT_RULE = (
    "10. EVENT RISK: the diagnostics score entries made inside a macro window (FOMC within 2 sessions, CPI/jobs next "
    "session), campaigns held through an FOMC decision, and the share of cycles where a Summarizer named a dated event "
    "the Decider never acknowledged. If in-window entries lose or acknowledgment is below 80%, the rule is an EVENT "
    "GATE clause with the number attached — the Decider is supplied an EVENT CALENDAR block. Falsified if 20 "
    "macro-window entries average better than the 20 nearest out-of-window entries."
)
FA_REASONING = (
    "The weekly review audited regime, geometry, re-entry and payoff but never scheduled events, so an unacknowledged "
    "FOMC decision or an earnings gap (MDB −15.2%) could not become a rule. feedback_diagnostics now computes "
    "macro-window entries, holds through an FOMC decision and the Summarizer→Decider acknowledgment rate; the soul "
    "(the text the weekly path actually executes) adds event windows to the audit order and the tracked patterns."
)

# ----------------------------------------------------------------------------- Summarizer texts
SA_EDITS = {
    "system_prompt": [
        ("5. EVENT RISK: scheduled earnings, macro prints, regulatory decisions visible in the inputs — name ticker and "
         "date. An earnings gap through a stop is the loss tail.",
         "5. EVENT RISK: scheduled binary events visible in the inputs — earnings dates, central-bank decisions (the "
         "Fed/FOMC and the rate path priced into it), macro prints (CPI, jobs report, PCE), regulatory or legal "
         "decisions, and geopolitical or policy shocks (war, tariffs, sanctions, an oil or Treasury-yield spike). Name "
         "the event, its date (or 'this week' / not_shown) and the tickers or sectors it gaps. An earnings gap through "
         "a stop is the loss tail; a Fed decision gaps every holding at once."),
        ("then the three setups, then EVENT RISK, ending with 'Watchlist: ...'",
         "then the three setups, then EVENT RISK (each scheduled event — Fed/FOMC, CPI/jobs, earnings, geopolitical "
         "shocks — with its date and what it gaps), ending with 'Watchlist: ...'"),
    ],
    "user_prompt_template": [
        ("scheduled events (earnings, macro, regulatory — with dates), synchronized coverage across outlets.",
         "scheduled events (earnings, Fed/FOMC decisions and the priced rate path, CPI/jobs prints, regulatory — with "
         "dates), geopolitical or policy shocks (war, tariffs, sanctions, oil/yield spikes), synchronized coverage "
         "across outlets."),
        ("the three setups, event risk, ending with 'Watchlist: ...'",
         "the three setups, event risk (each scheduled event with its date), ending with 'Watchlist: ...'"),
    ],
    "strategy_directives": [
        ("(4) scheduled event risk with dates;",
         "(4) scheduled event risk with dates — the next Fed/FOMC decision and the rate path priced into it, CPI/jobs "
         "prints, the earnings dates of the names you headline, and geopolitical or policy shocks (war, tariffs, "
         "oil/yield spikes);"),
    ],
    "soul": [
        ("- Flag sector rotations and regime shifts when visible.",
         "- Flag sector rotations and regime shifts when visible.\n"
         "- Name scheduled event risk every cycle — Fed/FOMC decisions, CPI/jobs prints, earnings dates, geopolitical "
         "or policy shocks — each with its date. The Decider reads an EVENT CALENDAR of dates; only you can see what "
         "the coverage says is priced in."),
    ],
    "memory": [
        ("then extension/crowding flags on headlined names, then catalysts.",
         "then extension/crowding flags on headlined names, then catalysts.\n"
         "- Scheduled event risk is context the screener cannot see: the next Fed/FOMC decision (date and priced rate "
         "path), CPI/jobs prints, the earnings dates of headlined names and geopolitical or policy shocks belong in "
         "every insights paragraph with their dates (2026-09-14: the Sep 16 FOMC was flagged in 8 of 36 summaries and "
         "consumed by nobody until the Decider got an EVENT GATE)."),
    ],
}
SA_DESCRIPTION = ("v{n} Summarizer (claude_code 2026-09-14) · EVENT RISK names Fed/FOMC decisions, CPI/jobs prints, "
                  "earnings dates and geopolitical/policy shocks with dates (system + user templates, decider_uses "
                  "directive, soul, memory) — the Decider now consumes them through the EVENT GATE")


# ----------------------------------------------------------------------------- helpers
def _llm_factory():
    """The dashboard's policy-graph model call, without importing the dashboard (Flask app + threads)."""
    from config import get_agent_model, get_agent_reasoning_level, get_reasoning_params

    def llm(role, system_text, user_text):
        from openai import OpenAI
        agent_name = "CriticAgent" if role == "critic" else "PromptEvolutionAgent"
        model = get_agent_model(agent_name)
        reasoning = get_reasoning_params(agent_name, model)
        print(f"🧬 Policy graph {role}: model={model} reasoning={get_agent_reasoning_level(agent_name)}")
        api_kwargs = dict(model=model, messages=[{"role": "system", "content": system_text},
                                                 {"role": "user", "content": user_text}])
        if reasoning:
            api_kwargs.update(reasoning)
        client = OpenAI()
        try:
            response = client.chat.completions.create(**api_kwargs)
        except Exception as exc:
            if "reasoning_effort" in api_kwargs and "reasoning_effort" in str(exc).lower():
                api_kwargs.pop("reasoning_effort", None)
                response = client.chat.completions.create(**api_kwargs)
            else:
                raise
        return response.choices[0].message.content if response and response.choices else ""
    return llm


def _context(config_hash):
    out = {}
    try:
        from feedback_diagnostics import SUPPLIED_DECIDER_FIELDS, compute_trade_diagnostics, format_diagnostics
        out["computed_diagnostics"] = format_diagnostics(compute_trade_diagnostics(config_hash, 30))
        out["decider_supplied_fields"] = SUPPLIED_DECIDER_FIELDS
    except Exception as exc:     # noqa: BLE001
        out["context_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _replace_all(text_, edits, label):
    for old, new in edits:
        if old not in text_:
            raise SystemExit(f"anchor not found in {label}: {old[:80]!r}")
        if text_.count(old) != 1:
            raise SystemExit(f"anchor not unique in {label}: {old[:80]!r}")
        text_ = text_.replace(old, new)
    return text_


def _run_proposal(engine, config_hash, agent_type, raw_files, reasoning, *, llm, is_margin_account, dry_run,
                  skip_critic, already_applied):
    from policy_graph import proposals as P
    from policy_graph import service
    from policy_graph.compile import compile_stored
    import prompt_manager

    ctx = service._Ctx(engine, config_hash, REPO_ROOT, is_margin_account)
    active = ctx.current_version(agent_type)
    if active is None:
        raise SystemExit(f"{agent_type}: no active version for {config_hash}")
    version = P._read(ctx, agent_type, active)
    if already_applied(version):
        print(f"↷ {agent_type} v{active} already carries the change — skipping")
        return None
    if callable(raw_files):          # edits need the live body of the base version
        raw_files = raw_files(version)
    files, new_fields = P.prepare(agent_type, config_hash, version, raw_files, is_margin_account=is_margin_account)
    print(f"\n=== {agent_type} v{active} → proposal ({len(files)} files) ===")
    for c in files:
        print(f"  {c.action:6} {c.id:48} kind={c.kind} primary={c.primary}")
        for line in c.diff[:40]:
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                print("      " + line[:160])
    if dry_run:
        stored = compile_stored(version)
        for f in sorted({c.field for c in files}):
            print(f"  [{f}] {len(stored.get(f) or '')} → {len(new_fields.get(f) or '')} chars")
        return None

    row = ctx.row(agent_type, active)
    pid = P._insert(engine, config_hash=config_hash, agent_type=agent_type, base_version=active,
                    base_prompt_version_id=row["id"], status="critiquing", created_by=CREATED_BY,
                    focus="event risk: scheduled binary events (FOMC / CPI / jobs / earnings) — operator request 2026-09-14",
                    patch={"reasoning": reasoning, "files": [c.to_dict() for c in files]})
    if skip_critic or llm is None:
        critic = {"verdict": "reject", "confidence": 0.0, "auto": False, "ship_first": None, "unexecutable_gates": [],
                  "reason": "critic skipped by the operator (--skip-critic); defer to human review.", "files": []}
    else:
        critic = P.run_critic(llm, agent_type, version, files, reasoning, _context(config_hash))
    review_id = P._record_review(engine, config_hash, agent_type, active, files, critic)
    P._update(engine, pid, status="review", critic=critic, critic_at=P._now(), review_id=review_id)
    print(f"  critic: {critic.get('verdict')} ({critic.get('confidence')}) — {critic.get('reason')}")
    for f in critic.get("files") or []:
        print(f"    {f.get('verdict'):7} {f.get('id')}: {f.get('reason')}")
    res = P.apply_proposal(engine, pid, [c.id for c in files], repo_root=REPO_ROOT, is_margin_account=is_margin_account,
                           activate=prompt_manager.set_active_prompt_version, actor=ACTOR)
    print(f"  ✅ applied proposal #{pid}: {agent_type} v{res['previous_version']} → v{res['version']} "
          f"(prompt_versions id {res['prompt_version_id']}); latest/: {(res.get('materialized') or {}).get('latest')}")
    return res


def _summarizer_version(engine, config_hash, *, is_margin_account, dry_run):
    from sqlalchemy import text
    from policy_graph import service
    from policy_graph.compile import compile_effective
    import prompt_manager

    ctx = service._Ctx(engine, config_hash, REPO_ROOT, is_margin_account)
    active = ctx.current_version("SummarizerAgent")
    row = ctx.row("SummarizerAgent", active)
    if "central-bank decisions" in (row.get("system_prompt") or ""):
        print(f"↷ SummarizerAgent v{active} already carries the EVENT RISK wording — skipping")
        return None
    v, _a, _b = service._ensure_and_read(ctx, "SummarizerAgent", active, materialized_by=CREATED_BY)
    effective = compile_effective(v)      # inherited soul/memory resolve to their default-file text
    fields = {}
    for f in ("system_prompt", "user_prompt_template", "strategy_directives", "soul", "memory"):
        base = row.get(f) or effective.get(f) or ""
        fields[f] = _replace_all(base, SA_EDITS.get(f, []), f"SummarizerAgent v{active} {f}")
    print(f"\n=== SummarizerAgent v{active} → new version (5 fields edited) ===")
    for f, edits in SA_EDITS.items():
        for old, new in edits:
            print(f"  [{f}] - {old[:100]}")
            print(f"  [{f}] + {new[:100]}")
    if dry_run:
        return None
    with engine.begin() as conn:
        new_version = int(conn.execute(text("""
            SELECT COALESCE(MAX(version), -1) + 1 FROM prompt_versions
            WHERE agent_type = 'SummarizerAgent' AND config_hash = :h
        """), {"h": config_hash}).scalar())
        description = SA_DESCRIPTION.replace("{n}", str(new_version))
        new_id = int(conn.execute(text("""
            INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template, strategy_directives,
                soul, memory, description, created_by, is_active, config_hash)
            VALUES ('SummarizerAgent', :v, :sp, :up, :sd, :soul, :mem, :d, :by, FALSE, :h) RETURNING id
        """), {"v": new_version, "sp": fields["system_prompt"], "up": fields["user_prompt_template"],
               "sd": fields["strategy_directives"], "soul": fields["soul"], "mem": fields["memory"],
               "d": description, "by": CREATED_BY, "h": config_hash}).scalar())
        prompt_manager.set_active_prompt_version(conn, "SummarizerAgent", config_hash, new_version,
                                                 action="manual_version", actor=ACTOR, reason=description)
    mat = service.ensure_materialized(engine, config_hash, "SummarizerAgent", new_version, repo_root=REPO_ROOT,
                                      is_margin_account=is_margin_account, materialized_by=CREATED_BY)
    print(f"  ✅ SummarizerAgent v{active} → v{new_version} (prompt_versions id {new_id}); latest/: {mat.get('latest')}")
    return {"version": new_version, "prompt_version_id": new_id}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", default=os.environ.get("CURRENT_CONFIG_HASH"),
                   help="live config hash (default: $CURRENT_CONFIG_HASH)")
    p.add_argument("--dry-run", action="store_true", help="validate and print the diffs; write nothing")
    p.add_argument("--skip-critic", action="store_true", help="record no model verdict (no API call)")
    p.add_argument("--only", choices=("decider", "feedback", "summarizer"), default=None)
    args = p.parse_args(argv)
    if not args.config_hash:
        p.error("--config-hash (or CURRENT_CONFIG_HASH) is required — never let a fresh shell generate one")
    os.environ["CURRENT_CONFIG_HASH"] = args.config_hash

    from config import IS_MARGIN_ACCOUNT, engine
    is_margin = bool(IS_MARGIN_ACCOUNT)
    llm = None if (args.dry_run or args.skip_critic) else _llm_factory()
    results = {}

    if args.only in (None, "decider"):
        raw = [
            {"id": "DA.directives.strategy.event_gate", "action": "add", "parent": "DA.directives.strategy",
             "title": "EVENT GATE", "body": DECIDER_GATE, "primary": True,
             "what": "Adds an EVENT GATE: half size and D ≤2% inside a macro window (FOMC within 2 sessions, CPI/jobs next "
                     "session), reject candidates reporting inside 5 sessions, sell/trim holdings reporting within 2 sessions.",
             "why": "0 of 96 decisions in 30 days acknowledged a scheduled event the Summarizers flagged 8×/day; MDB −15.2% "
                    "(2026-09-02) was an earnings gap through an unpriced kill.",
             "expected_effect": "Fewer positions sit unpriced through FOMC / CPI / jobs / earnings; in-window entries are "
                                "half size with a 2% kill, and every such reason names the event so the feedback loop can score it.",
             "falsified_if": "20 in-window half-size entries taken under this gate average better than the 20 nearest "
                             "out-of-window entries."},
            {"id": "DA.soul.risk_management", "action": "edit", "primary": False, "body": None,
             "what": "Risk-Management bullet: a scheduled binary event is a gap, not noise (same thresholds as the gate).",
             "why": "The soul is the identity the Decider reads before the gates; the MDB earnings gap is the paid-for lesson.",
             "expected_effect": "Consistent behaviour between identity and gate."},
            {"id": "DA.memory.lessons.event_risk", "action": "add", "parent": "DA.memory.lessons", "title": "#event-risk",
             "body": DECIDER_LESSON, "primary": False,
             "what": "Lesson #event-risk with the thresholds and the audit numbers.",
             "why": "Every Decider change lands in prompt + SOUL + MEMORY together; lessons are always served.",
             "expected_effect": "The lesson is citable by id and carries its own win rate."},
        ]

        def _soul_body(version):
            node = version.nodes["DA.soul.risk_management"]
            if DECIDER_SOUL_ANCHOR not in node.body:
                raise SystemExit("DA.soul.risk_management anchor missing")
            lines = node.body.split("\n")
            idx = next(i for i, l in enumerate(lines) if l.startswith(DECIDER_SOUL_ANCHOR))
            lines.insert(idx + 1, DECIDER_SOUL_BULLET)
            return "\n".join(lines)

        def _prep(version):
            raw[1]["body"] = _soul_body(version)
            return raw

        results["decider"] = _run_proposal(
            engine, args.config_hash, "DeciderAgent", _prep, DECIDER_REASONING, llm=llm,
            is_margin_account=is_margin, dry_run=args.dry_run, skip_critic=args.skip_critic,
            already_applied=lambda v: any(i.endswith(".event_gate") for i in v.nodes))

    if args.only in (None, "feedback"):
        def _fa_prep(version):
            node = version.nodes["FA.soul.review_style"]
            return [
                {"id": "FA.soul.review_style", "action": "edit", "primary": True,
                 "body": _replace_all(node.body, FA_SOUL_EDITS, "FA.soul.review_style"),
                 "what": "Event windows join the audit order and the tracked patterns (the weekly path executes the soul).",
                 "why": "feedback_diagnostics now computes macro-window entries, holds through FOMC and the Summarizer→Decider "
                        "acknowledgment rate (0 of 96 decisions acknowledged a flagged event before 2026-09-14).",
                 "expected_effect": "Weekly reviews score event windows and can turn a losing window into an EVENT GATE clause.",
                 "falsified_if": "Over the next 4 weekly reviews the event-risk diagnostic is never cited while macro-window "
                                 "entries underperform out-of-window entries."},
                {"id": "FA.directives.audit_order.event_risk", "action": "add", "parent": "FA.directives.audit_order",
                 "title": "EVENT RISK", "body": FA_AUDIT_RULE, "primary": False,
                 "what": "Audit step 10: event risk.", "why": "Record of the same rule on the manual review path.",
                 "expected_effect": "Manual reviews audit the same numbers."},
            ]
        results["feedback"] = _run_proposal(
            engine, args.config_hash, "FeedbackAgent", _fa_prep, FA_REASONING, llm=llm,
            is_margin_account=is_margin, dry_run=args.dry_run, skip_critic=args.skip_critic,
            already_applied=lambda v: "event windows" in v.nodes["FA.soul.review_style"].body)

    if args.only in (None, "summarizer"):
        results["summarizer"] = _summarizer_version(engine, args.config_hash, is_margin_account=is_margin,
                                                    dry_run=args.dry_run)

    print("\nresult:", json.dumps(results, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
