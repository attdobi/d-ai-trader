#!/usr/bin/env python
"""Plain gates, 2026-09-16 — the operator asked for rules a reader can follow and for the prompts that
generate rules to demand the same. Three attributable steps through the policy graph (idempotent, dry-run first):

  1. FeedbackAgent: edit FA.soul.rule_style — the weekly loop executes the soul, so this is where the plain-gate
     shape ("N. LABEL — IF <condition> THEN <action>. Otherwise next gate. Falsified if …", ≤ 240 chars) lands.
  2. DeciderAgent: the EVENT GATE (767 chars, three conditions; the critic asked for a split) becomes three plain
     gates: EVENT GATE (macro window), EARNINGS CANDIDATE, EARNINGS HOLDING — same thresholds, one condition each.
  3. DeciderAgent: the #event-risk lesson and the Risk-Management soul bullet rewritten in plain words, same numbers.

    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_plain_rules.py --dry-run
    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_plain_rules.py [--skip-critic] [--only feedback|gates|lesson]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ACTOR = "claude_code (operator: Attila Dobi, 2026-09-16)"

FA_RULE_STYLE = (
    "## Rule Style (plain gates)\n"
    "When I write or rewrite a Decider rule — a weekly reminder rule, a proposal, a rewrite — it is a plain gate a "
    "first-time reader can execute, in this exact shape: \"N. LABEL — IF <one condition on a field the Decider is supplied, "
    "with its number> THEN <one action: pass / half size / full size / SELL / HOLD>. Otherwise next gate. Falsified if "
    "<which number over how many trades proves it wrong>.\" Supplied fields: the INDEX REGIME line, the EVENT CALENDAR "
    "block, % vs the 20d MA, the K:/D: kill line, the QUARANTINE line, Holdings, the watchlist row. One condition per "
    "gate, at most 240 characters, the number inside the sentence, no parentheses, no abbreviation the Decider is not "
    "supplied. The first gate that fires decides; later gates only refine size or exits. I keep the \"N. LABEL — text\" "
    "form so each gate stays one guideline the Decider cites by id, I never combine two conditions in one gate, and I "
    "change one gate at a time, measured by its hits and win rate."
)

EVENT_GATE = (
    "9. EVENT GATE — IF the EVENT CALENDAR block says MACRO WINDOW: YES (an FOMC decision within 2 sessions, or a CPI or "
    "jobs print next session) THEN at most 1 half-size BUY with D ≤2%, naming the event and its date in the reason. "
    "Otherwise next gate. Falsified if 20 in-window entries beat the 20 nearest out-of-window entries."
)
EARNINGS_CANDIDATE = (
    "10. EARNINGS CANDIDATE — IF a BUY candidate reports earnings within the next 5 sessions THEN reject it and write "
    "\"earnings <date> inside hold window\". Otherwise next gate. Falsified if 20 such candidates average better than "
    "+1% over their next 5 sessions."
)
EARNINGS_HOLDING = (
    "11. EARNINGS HOLDING — IF a holding reports earnings within 2 sessions THEN SELL before the print, or TRIM to half "
    "only when RISK-ON and the position is up 3% or more. Otherwise hold by the earlier gates. Falsified if 20 holdings "
    "kept through their print average better than +1%."
)
LESSON = (
    "- **#event-risk — Scheduled events gap through kills.** In a macro window (EVENT CALENDAR block) buy at most 1 "
    "half-size with D ≤2% and name the event; reject a candidate reporting within 5 sessions; sell or trim a holding "
    "reporting within 2 sessions. [[MDB]] −15.2% on 2026-09-02 was an earnings gap."
)
TIGHT = {
    "DA.directives.strategy.event_gate": (
        "9. EVENT GATE — IF the EVENT CALENDAR block shows MACRO WINDOW: YES THEN at most 1 half-size BUY with D ≤2%, "
        "naming the event and its date in the reason. Otherwise next gate. Falsified if 20 in-window entries beat the "
        "20 nearest out-of-window entries."),
    "DA.directives.strategy.earnings_candidate": (
        "10. EARNINGS CANDIDATE — IF a BUY candidate reports earnings within the next 5 sessions THEN reject it, writing "
        "\"earnings <date> inside hold window\". Falsified if 20 such candidates average better than +1% over their next 5 sessions."),
    "DA.directives.strategy.earnings_holding": (
        "11. EARNINGS HOLDING — IF a holding reports earnings within 2 sessions THEN SELL before the print, or TRIM to "
        "half only when RISK-ON and up 3% or more. Falsified if 20 holdings kept through their print average better than +1%."),
}
SOUL_ANCHOR = "- **A scheduled binary event is a gap, not noise.**"
SOUL_BULLET = (
    "- **A scheduled event is a gap, not noise.** A kill protects against drift, not a gap: an FOMC decision, a CPI or "
    "jobs print, or an earnings date inside the hold can jump straight through it. Read the EVENT CALENDAR block with "
    "the regime. Inside a window buy small or not at all, and never hold a name through its own print. (Paid for by "
    "[[MDB]] −15.2%, 2026-09-02.)"
)


def _llm_factory():
    from config import get_agent_model, get_agent_reasoning_level, get_reasoning_params

    def llm(role, system_text, user_text):
        from openai import OpenAI
        agent_name = "CriticAgent" if role == "critic" else "PromptEvolutionAgent"
        model = get_agent_model(agent_name)
        reasoning = get_reasoning_params(agent_name, model)
        print(f"🧬 Policy graph {role}: model={model} reasoning={get_agent_reasoning_level(agent_name)}")
        kw = dict(model=model, messages=[{"role": "system", "content": system_text}, {"role": "user", "content": user_text}])
        if reasoning:
            kw.update(reasoning)
        client = OpenAI()
        try:
            r = client.chat.completions.create(**kw)
        except Exception as exc:
            if "reasoning_effort" in kw and "reasoning_effort" in str(exc).lower():
                kw.pop("reasoning_effort", None)
                r = client.chat.completions.create(**kw)
            else:
                raise
        return r.choices[0].message.content if r and r.choices else ""
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", default=os.environ.get("CURRENT_CONFIG_HASH"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-critic", action="store_true")
    p.add_argument("--only", choices=("feedback", "gates", "lesson", "tighten", "order"), default=None)
    args = p.parse_args(argv)
    if not args.config_hash:
        p.error("--config-hash (or CURRENT_CONFIG_HASH) is required — never let a fresh shell generate one")
    os.environ["CURRENT_CONFIG_HASH"] = args.config_hash

    from config import IS_MARGIN_ACCOUNT, engine
    import prompt_manager
    from policy_graph.operator import apply_hand_authored, maintenance_version
    common = dict(repo_root=REPO_ROOT, is_margin_account=bool(IS_MARGIN_ACCOUNT), actor=ACTOR, dry_run=args.dry_run,
                  llm=(None if (args.dry_run or args.skip_critic) else _llm_factory()),
                  activate=prompt_manager.set_active_prompt_version, context=_context(args.config_hash))
    results = {}

    if args.only in (None, "feedback"):
        def fa_files(version):
            node = version.nodes["FA.soul.rule_style"]
            return [{"id": "FA.soul.rule_style", "action": "edit", "primary": True, "body": FA_RULE_STYLE,
                     "what": "Rule style becomes the plain-gate shape: IF <condition> THEN <action>; otherwise next gate; ≤ 240 chars.",
                     "why": "The operator found the current gates unreadable (EVENT GATE 767 chars, PRICED KILL 572); the weekly loop writes rules from this soul section.",
                     "expected_effect": "Weekly reminder rules become one-condition gates a first-time reader can execute.",
                     "falsified_if": "Over the next 4 weekly reviews any generated rule exceeds 240 characters or tests two conditions."}]
        results["feedback"] = apply_hand_authored(
            engine, args.config_hash, "FeedbackAgent", fa_files,
            "The operator asked for rules a reader can follow. The soul's Rule Style section is what the weekly path executes, "
            "so the plain-gate shape lands there; the drafter and critic prompts in code carry the same shape.",
            focus="plain gates — operator request 2026-09-16",
            already_applied=lambda v: "plain gate" in v.nodes["FA.soul.rule_style"].body, **common)

    if args.only in (None, "gates"):
        def gate_files(version):
            return [
                {"id": "DA.directives.strategy.event_gate", "action": "edit", "primary": True, "body": EVENT_GATE,
                 "what": "EVENT GATE keeps only the macro-window condition (FOMC within 2 sessions or today before 2 pm ET; CPI/jobs next session), written as a plain gate.",
                 "why": "767-character gate with three conditions; the critic asked for a split and the operator for readability. Thresholds unchanged.",
                 "expected_effect": "Same behaviour, one condition per gate, citable separately so each clause earns its own win rate.",
                 "falsified_if": "20 in-window entries average better than the 20 nearest out-of-window entries."},
                {"id": "DA.directives.strategy.earnings_candidate", "action": "add", "parent": "DA.directives.strategy",
                 "title": "EARNINGS CANDIDATE", "body": EARNINGS_CANDIDATE, "primary": False,
                 "what": "Candidate reporting within 5 sessions → reject (moved out of the EVENT GATE).",
                 "why": "One condition per gate.", "expected_effect": "Unchanged behaviour, separately measurable."},
                {"id": "DA.directives.strategy.earnings_holding", "action": "add", "parent": "DA.directives.strategy",
                 "title": "EARNINGS HOLDING", "body": EARNINGS_HOLDING, "primary": False,
                 "what": "Holding reporting within 2 sessions → sell or trim (moved out of the EVENT GATE).",
                 "why": "One condition per gate.", "expected_effect": "Unchanged behaviour, separately measurable."},
            ]
        results["gates"] = apply_hand_authored(
            engine, args.config_hash, "DeciderAgent", gate_files,
            "Readability and attribution: the EVENT GATE bundled a macro-window rule with two earnings rules in 767 characters. "
            "Same thresholds, three plain gates, each citable on its own.",
            focus="plain gates — split EVENT GATE (operator request 2026-09-16)",
            already_applied=lambda v: any(i.endswith(".earnings_candidate") for i in v.nodes), **common)

    if args.only in (None, "lesson"):
        def lesson_files(version):
            node = version.nodes["DA.soul.risk_management"]
            if SOUL_ANCHOR not in node.body:
                raise SystemExit("soul anchor missing")
            lines = node.body.split("\n")
            idx = next(i for i, l in enumerate(lines) if l.startswith(SOUL_ANCHOR))
            lines[idx] = SOUL_BULLET
            return [
                {"id": "DA.memory.lessons.event_risk", "action": "edit", "primary": True, "body": LESSON,
                 "what": "Lesson #event-risk in plain words, same numbers.",
                 "why": "572-character lesson; the operator found it unreadable.",
                 "expected_effect": "Same rule, readable.",
                 "falsified_if": "The lesson is cited less than 3 times over the next 20 cycles that carry a macro window."},
                {"id": "DA.soul.risk_management", "action": "edit", "primary": False, "body": "\n".join(lines),
                 "what": "Risk-Management event bullet in plain words, same numbers.", "why": "Readability.",
                 "expected_effect": "None beyond clarity."},
            ]
        results["lesson"] = apply_hand_authored(
            engine, args.config_hash, "DeciderAgent", lesson_files,
            "Plain-language rewrite of the event lesson and soul bullet; every number is unchanged.",
            focus="plain words — event lesson + soul bullet (operator request 2026-09-16)",
            already_applied=lambda v: "Scheduled events gap through kills" in v.nodes["DA.memory.lessons.event_risk"].body, **common)

    if args.only in (None, "tighten"):
        def tight_files(version):
            out = []
            for i, (nid, body) in enumerate(TIGHT.items()):
                if nid not in version.nodes:
                    raise SystemExit(f"{nid} missing — run the gates step first")
                out.append({"id": nid, "action": "edit", "primary": i == 0, "body": body,
                            "what": f"{nid.split('.')[-1].replace('_', ' ').upper()} shortened to {len(body)} characters, same thresholds.",
                            "why": "The critic and the style lint flagged 255-324 character gates against the 240 bar the plain-gate style sets.",
                            "expected_effect": "Same behaviour; the gate reads in one breath.",
                            "falsified_if": "20 in-window entries beat the 20 nearest out-of-window entries."})
            return out
        results["tighten"] = apply_hand_authored(
            engine, args.config_hash, "DeciderAgent", tight_files,
            "Readability only: the three event gates trimmed to the 240-character bar; every threshold unchanged. The macro window "
            "itself (FOMC within 2 sessions or today before 2 pm ET; CPI or jobs print next session) is computed by the EVENT "
            "CALENDAR block, which prints MACRO WINDOW: YES with the reason, so the gate tests that field directly.",
            focus="plain gates — tighten to 240 chars (operator request 2026-09-16)",
            already_applied=lambda v: all(v.nodes[k].body == b for k, b in TIGHT.items() if k in v.nodes), **common)

    if args.only in (None, "order"):
        # maintenance, not a policy step: v31 compiled the gates as 9, 11, 10 (apply_patch inserted the second add
        # before the first — fixed in proposals.apply_patch), and the critic asked for gate 9 at ≤ 240 characters.
        gate9_old = TIGHT["DA.directives.strategy.event_gate"]
        gate9_new = gate9_old.replace(" Otherwise next gate.", "")

        def reorder(fields):
            sd = fields["strategy_directives"]
            lines = sd.split("\n")
            i10 = next((i for i, l in enumerate(lines) if l.startswith("10. EARNINGS CANDIDATE")), None)
            i11 = next((i for i, l in enumerate(lines) if l.startswith("11. EARNINGS HOLDING")), None)
            if i10 is not None and i11 is not None and i11 < i10:
                lines[i10], lines[i11] = lines[i11], lines[i10]
            sd = "\n".join(lines)
            if gate9_old in sd:
                sd = sd.replace(gate9_old, gate9_new)
            fields["strategy_directives"] = sd
            return fields
        results["order"] = maintenance_version(
            engine, args.config_hash, "DeciderAgent", reorder,
            "v{n} Decider (maintenance, claude_code 2026-09-16) · gates 10/11 back in numeric order (apply_patch bug, fixed) · "
            "EVENT GATE trimmed to 231 chars (critic on proposal #7)",
            repo_root=REPO_ROOT, is_margin_account=bool(IS_MARGIN_ACCOUNT), activate=prompt_manager.set_active_prompt_version,
            actor=ACTOR, dry_run=args.dry_run)

    print("\nresult:", json.dumps(results, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
