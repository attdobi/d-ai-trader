#!/usr/bin/env python
"""Plain-language pass over Decider gates 1–8, one proposal per gate (2026-09-16, operator request).

Every threshold stays what it was; each gate is rewritten in the plain shape ("N. LABEL — IF <condition>
THEN <action>. Otherwise next gate. Falsified if <metric>."), the two label-less gates get labels, and
PRICED KILL — which carried the entry sizing and the binding exit in one 586-character paragraph — keeps the
entry half and hands the exit half to a new gate, KILL BREACH. Where a gate had no falsification metric one is
added and said so. Each step is its own proposal: the critic verifies that the diff preserves the numbers,
the verdict is recorded, the operator applies (actor named).

    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_plain_gates.py --dry-run
    CURRENT_CONFIG_HASH=9ea09b9as ./dai/bin/python apply_plain_gates.py [--only regime_gate ...] [--skip-critic]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ACTOR = "claude_code (operator: Attila Dobi, 2026-09-16)"
S = "DA.directives.strategy"

# (slug of the existing gate, new body, note for the critic, extra files)
GATES = [
    ("regime_gate",
     "1. REGIME GATE — IF INDEX REGIME is RISK-ON THEN up to 3 new BUYs, full rails. IF MIXED THEN at most 2 new BUYs "
     "at half size, extension ≤5%. IF RISK-OFF THEN cash by default: at most 1 half-size BUY, oversold reversal or ≤3% "
     "above the 20d MA only, harvest at +2%. Falsified if 20 RISK-OFF entries average worse than −1%.",
     "Same three regime tiers and numbers; the tiers stay in one gate because they are one field with three values."),
    ("extension_cap",
     "2. EXTENSION CAP — IF a name is ≤5% above its 20d MA THEN full size. IF 5–8% above THEN half size, RISK-ON only. "
     "IF more than 8% above THEN reject it as a chase. Falsified if 20 rejected names above 8% would have averaged "
     "better than +1.5% over the next 3 sessions.",
     "Same tiers (≤5%, 5–8% RISK-ON only, >8% reject) and the same falsifier."),
    ("priced_kill",
     "3. PRICED KILL — Every BUY reason ends with K:<price>;D:<%>: K is the higher of the 20d MA or stated support and "
     "current price × 0.97, D its distance. IF D ≤3% THEN full size; IF D ≤6% THEN half size; IF D >6% THEN pass. "
     "Falsified if 20 entries sized half at D 3–6% beat 20 sized full at D ≤3%.",
     "Entry half only, same K formation and size tiers; the binding exit moves to KILL BREACH (gate 12) with the "
     "original falsifier; this gate gets a sizing falsifier of its own."),
    ("re_entry_quarantine",
     "4. RE-ENTRY QUARANTINE — IF the ticker is on the QUARANTINE line or was exited within 2 sessions THEN no BUY; after "
     "a losing exit also wait for a reclaim of the failed level or a new catalyst. Falsified if 15 quarantined names "
     "would have averaged better than +1% over the next 3 sessions.",
     "Same 2-session quarantine, same reclaim-or-new-catalyst condition after a loss, same falsifier."),
    ("correlation",
     "5. CORRELATION — IF a BUY would make more than 2 semiconductor, AI-infrastructure, quantum or space names held at "
     "once THEN reject it; those names are one book with one risk budget. Falsified if 10 rejected third names would "
     "have averaged better than +1.5% over the next 3 sessions.",
     "Same cap of 2; a falsification metric is added because the gate had none."),
    ("harvest",
     "6. HARVEST — IF a holding is up 3% or more (2% in RISK-OFF) THEN SELL all or most of it, unless a catalyst no "
     "older than 1 session is still price-confirmed and the regime is RISK-ON. Falsified if 20 harvested winners would "
     "have gained 2% more over the next 3 sessions.",
     "Same +3% / +2% thresholds and the same RISK-ON fresh-catalyst exception; the 'stop distance is the lever' sentence "
     "already lives in the soul's Payoff math bullet; a falsifier is added because the gate had none."),
    ("n7",
     "7. DAY CHASE — IF a name is up 8% or more on the day, or has gapped or gone parabolic THEN reject it. Missing VWAP, "
     "10m or 1h data never disqualifies a setup; judge headlines by event time, source and ticker specificity. Falsified "
     "if 20 rejected names would have averaged better than +1.5% over the next 3 sessions.",
     "Same ≥8%-day / gap / parabolic rejection, the headline audit and the intraday allowance kept in one sentence each; "
     "the gate gets the label DAY CHASE (its id changes from n7 to day_chase) and a falsifier."),
    ("n8",
     "8. CANDIDATES — Weigh 2–3 candidates each cycle and rank accepted BUYs R1..Rk from supplied evidence only, within "
     "settled funds, rails, ticket limits, cooldowns and the 5-holding cap. Falsified if 20 cycles that weighed one "
     "candidate outperform 20 cycles that weighed 2–3.",
     "Same procedure and limits; labelled CANDIDATES (id n8 → candidates) with a falsifier added."),
]
KILL_BREACH = (
    "12. KILL BREACH — IF a holding's current price is at or below its K THEN SELL it in full before any HOLD or new "
    "BUY; no confirmation, grace, averaging or waiting for a close overrides it. No numeric K means K = cost × 0.97. "
    "Falsified if the next 20 K-breach exits average a realized loss worse than −3.5%."
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
    out["operator_note"] = ("Plain-language pass requested by the operator: judge whether every number and action of the old "
                            "text survives in the new text; wording-only changes are the point of this step.")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", default=os.environ.get("CURRENT_CONFIG_HASH"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-critic", action="store_true")
    p.add_argument("--only", action="append", default=None, help="gate slug(s) to run (default: all, in order); 'fixups' = the critic's wording catches")
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
    for slug, body, note, in [(g[0], g[1], g[2]) for g in GATES]:
        if args.only and slug not in args.only:
            continue
        node_id = f"{S}.{slug}"

        def files(version, node_id=node_id, body=body, note=note, slug=slug):
            if node_id not in version.nodes:
                raise SystemExit(f"{node_id} is not in the active version (already renamed?)")
            out = [{"id": node_id, "action": "edit", "primary": True, "body": body,
                    "what": f"{slug.replace('_', ' ').upper()} rewritten as a plain gate ({len(body)} characters).",
                    "why": note, "expected_effect": "Same behaviour; a first-time reader can execute the gate.",
                    "falsified_if": body[body.lower().rfind("falsified if"):] if "falsified if" in body.lower() else "wording only"}]
            if slug == "priced_kill":
                out.append({"id": f"{S}.kill_breach", "action": "add", "parent": S, "title": "KILL BREACH", "body": KILL_BREACH,
                            "primary": False, "what": "The binding exit half of PRICED KILL as its own gate, with the original falsifier.",
                            "why": "One condition per gate; the exit rule is the one the Decider cites most.",
                            "expected_effect": "Unchanged behaviour, separately citable."})
            return out

        def done(version, node_id=node_id, body=body):
            n = version.nodes.get(node_id)
            return n is not None and n.body == body

        results[slug] = apply_hand_authored(
            engine, args.config_hash, "DeciderAgent", files,
            f"Plain-language rewrite of gate {slug} on the operator's request; every threshold unchanged. {note}",
            focus=f"plain gates — {slug} (operator request 2026-09-16)", already_applied=done, **common)
    if args.only and "fixups" in args.only:
        # The critic read every diff (proposals #8–#15) and caught three wording drifts; restore them verbatim.
        FIXUPS = [
            ("1. REGIME GATE — IF INDEX REGIME is RISK-ON", "1. REGIME GATE — First, every cycle: IF INDEX REGIME is RISK-ON"),
            ("wait for a reclaim of the failed level or a new catalyst.", "wait for a reclaim of the failed level or a genuinely new catalyst."),
            ("judge headlines by event time, source and ticker specificity.",
             "judge headlines by event time vs article time, primary vs recycled, hard event vs analyst opinion, ticker-specific vs indirect."),
            ("THEN SELL it, all or most of it, unless", "THEN SELL it in full or in majority, unless"),
            ("THEN SELL all or most of it, unless", "THEN SELL it in full or in majority, unless"),
            ("outperform 20 cycles that weighed 2–3.", "average better than 20 cycles that weighed 2–3."),
        ]

        def fix(fields):
            sd = fields["strategy_directives"]
            for old, new in FIXUPS:
                if sd.count(old) == 1:
                    sd = sd.replace(old, new)
            fields["strategy_directives"] = sd
            return fields
        results["fixups"] = maintenance_version(
            engine, args.config_hash, "DeciderAgent", fix,
            "v{n} Decider (maintenance, claude_code 2026-09-16) · critic catches on the plain-gate pass restored: 'First, every cycle' "
            "(REGIME GATE), 'genuinely new catalyst' (RE-ENTRY QUARANTINE), the full headline-audit list (DAY CHASE), an explicit "
            "sale quantity (HARVEST), 'average better than' (CANDIDATES)",
            repo_root=REPO_ROOT, is_margin_account=bool(IS_MARGIN_ACCOUNT), activate=prompt_manager.set_active_prompt_version,
            actor=ACTOR, dry_run=args.dry_run)

    print("\nresult:", json.dumps({k: (v and {"version": v.get("version"), "proposal": v.get("proposal_id")}) for k, v in results.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
