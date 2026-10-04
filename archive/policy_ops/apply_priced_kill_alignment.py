"""One-off operator step (2026-10-04): align gate 3 PRICED KILL and its lesson with the 1.3% rule.

Prompt Lab v44 (2026-09-20, human-approved) put "IF numeric D is missing or D >1.3% THEN PASS" into the
system template's PRICED KILL step, and the user template tells the Decider to follow that stricter rule.
Gate 3 and the #priced-kill lesson still describe the old ladder (D ≤3% full, ≤6% half, >6% pass). The 6% tier
can never fire, because K is at least current price × 0.97, so D is never above 3%. This edits the gate (primary)
and the lesson (supporting) so all three texts say the same thing. Idempotent; `--dry-run` first.

    ./dai/bin/python archive/policy_ops/apply_priced_kill_alignment.py --config-hash 9ea09b9as --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # archived under archive/policy_ops/
sys.path.insert(0, str(REPO_ROOT))
ACTOR = "claude_code"

GATE_ID = "DA.directives.strategy.priced_kill"
LESSON_ID = "DA.memory.lessons.priced_kill"
GATE = ("3. PRICED KILL — Every BUY reason ends with K:<price>;D:<%>: K is the higher of the 20d MA or stated support "
        "and current price × 0.97, D its distance. IF D is missing or above 1.3% THEN pass. Otherwise size by the "
        "REGIME GATE. Falsified if 20 entries with D ≤1.3% average below 0%.")
LESSON = ("- **#priced-kill — A kill is a price.** Write `K:<price>;D:<%>` on every BUY from supplied numbers (higher of "
          "20d MA / stated support and entry × 0.97). D missing or above 1.3% = pass. Binding on the first breach.")


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
        r = OpenAI().chat.completions.create(**kw)
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
    out["operator_note"] = ("Consistency fix requested by the operator: the human-approved Prompt Lab v44 system template already "
                            "passes any BUY with D missing or above 1.3% and the user template says to follow it. This patch makes "
                            "gate 3 and its lesson state the same rule. Judge whether the new text matches the system rule exactly.")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", default=os.environ.get("CURRENT_CONFIG_HASH"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-critic", action="store_true")
    args = p.parse_args(argv)
    if not args.config_hash:
        p.error("--config-hash (or CURRENT_CONFIG_HASH) is required — never let a fresh shell generate one")
    os.environ["CURRENT_CONFIG_HASH"] = args.config_hash

    from config import IS_MARGIN_ACCOUNT, engine
    import prompt_manager
    from policy_graph.operator import apply_hand_authored

    def files(version):
        for nid in (GATE_ID, LESSON_ID):
            if nid not in version.nodes:
                raise SystemExit(f"{nid} is not in the active version")
        return [
            {"id": GATE_ID, "action": "edit", "primary": True, "body": GATE,
             "what": "Gate 3 states the 1.3% rule the system template already enforces, instead of the 3%/6% ladder.",
             "why": "Prompt Lab v44 (human-approved 2026-09-20) made the system PRICED KILL pass any BUY with D missing or "
                    "above 1.3%; the gate still said full size to 3% and half to 6%, two contradicting texts in one prompt.",
             "expected_effect": "No behaviour change intended: the Decider already follows the stricter system rule; the "
                                "prompt stops contradicting itself and citations of gate 3 mean one thing.",
             "falsified_if": "Falsified if 20 entries with D ≤1.3% average below 0%."},
            {"id": LESSON_ID, "action": "edit", "primary": False, "body": LESSON,
             "what": "The #priced-kill lesson drops 'no priced kill within 6% = pass' for the 1.3% rule.",
             "why": "Same contradiction as gate 3; the 6% tier could never fire because K ≥ current price × 0.97.",
             "expected_effect": "Lesson and gate agree with the system template."},
        ]

    def done(version):
        g, l = version.nodes.get(GATE_ID), version.nodes.get(LESSON_ID)
        return g is not None and l is not None and g.body == GATE and l.body == LESSON

    res = apply_hand_authored(
        engine, args.config_hash, "DeciderAgent", files,
        "Consistency fix: gate 3 and the #priced-kill lesson restate the 1.3% PRICED KILL rule that the human-approved "
        "Prompt Lab v44 system template already enforces.",
        repo_root=REPO_ROOT, is_margin_account=bool(IS_MARGIN_ACCOUNT), actor=ACTOR, dry_run=args.dry_run,
        llm=(None if (args.dry_run or args.skip_critic) else _llm_factory()),
        activate=prompt_manager.set_active_prompt_version, context=_context(args.config_hash),
        focus="PRICED KILL consistency with the v44 system template (operator request 2026-10-04)", already_applied=done)
    print("result:", res and {"version": res.get("version"), "proposal": res.get("proposal_id")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
