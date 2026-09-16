"""Hand-authored proposals — the operator (or Claude Code on the operator's instruction) writes the guideline
files; the proposal still goes through the same validation, round trip, critic verdict and record as a drafted
one, and is applied with the actor named. Used by the one-off apply_*.py scripts.

    apply_hand_authored(engine, config_hash, "DeciderAgent", files_fn, reasoning, llm=llm, activate=activate, ...)

`files_fn(version) -> [raw file dicts]` builds the patch against the live base version (edits need its bodies);
`llm(role, system, user) -> str` is the dashboard's model call (None = record no critic verdict);
`activate` is prompt_manager.set_active_prompt_version. Never imports config.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import proposals as P
from . import service
from .compile import compile_stored

CREATED_BY = "claude_code"


def apply_hand_authored(engine, config_hash: str, agent_type: str, files_fn: Callable, reasoning: str, *, repo_root,
                        is_margin_account: bool, llm=None, activate=None, actor: str, focus: str = "",
                        already_applied: Optional[Callable] = None, context: Optional[dict] = None,
                        dry_run: bool = False, log=print) -> Optional[dict]:
    ctx = service._Ctx(engine, config_hash, repo_root, is_margin_account)
    active = ctx.current_version(agent_type)
    if active is None:
        raise SystemExit(f"{agent_type}: no active version for {config_hash}")
    version = P._read(ctx, agent_type, active)
    if already_applied is not None and already_applied(version):
        log(f"↷ {agent_type} v{active} already carries the change — skipping")
        return None
    raw_files = files_fn(version)
    files, new_fields = P.prepare(agent_type, config_hash, version, raw_files, is_margin_account=is_margin_account)
    style = P.style_check(files)
    log(f"\n=== {agent_type} v{active} → proposal ({len(files)} files) ===")
    for c in files:
        log(f"  {c.action:6} {c.id:48} kind={c.kind} primary={c.primary} chars={len(c.body or '')}")
        for line in c.diff[:40]:
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                log("      " + line[:160])
    for w in style:
        log(f"  style: {w['id']}: {w['warning']}")
    if dry_run:
        stored = compile_stored(version)
        for f in sorted({c.field for c in files}):
            log(f"  [{f}] {len(stored.get(f) or '')} → {len(new_fields.get(f) or '')} chars")
        return None
    if activate is None:
        raise SystemExit("activate (prompt_manager.set_active_prompt_version) is required to apply")
    row = ctx.row(agent_type, active)
    pid = P._insert(engine, config_hash=config_hash, agent_type=agent_type, base_version=active,
                    base_prompt_version_id=row["id"], status="critiquing", created_by=CREATED_BY,
                    focus=(focus or "")[:2000] or None,
                    patch={"reasoning": reasoning, "files": [c.to_dict() for c in files], "style": style})
    if llm is None:
        critic = {"verdict": "reject", "confidence": 0.0, "auto": False, "ship_first": None, "unexecutable_gates": [],
                  "reason": "critic skipped by the operator; defer to human review.", "files": []}
    else:
        critic = P.run_critic(llm, agent_type, version, files, reasoning, context or {})
    review_id = P._record_review(engine, config_hash, agent_type, active, files, critic)
    P._update(engine, pid, status="review", critic=critic, critic_at=P._now(), review_id=review_id)
    log(f"  critic: {critic.get('verdict')} ({critic.get('confidence')}) — {critic.get('reason')}")
    for f in critic.get("files") or []:
        log(f"    {str(f.get('verdict')):7} {f.get('id')}: {f.get('reason')}")
    res = P.apply_proposal(engine, pid, [c.id for c in files], repo_root=repo_root, is_margin_account=is_margin_account,
                           activate=activate, actor=actor)
    log(f"  ✅ applied proposal #{pid}: {agent_type} v{res['previous_version']} → v{res['version']} "
        f"(prompt_versions id {res['prompt_version_id']}); latest/: {(res.get('materialized') or {}).get('latest')}")
    return res


def maintenance_version(engine, config_hash: str, agent_type: str, transform, description: str, *, repo_root,
                        is_margin_account: bool, activate, actor: str, dry_run: bool = False, log=print) -> Optional[dict]:
    """A plain version row for maintenance that is not a policy step (ordering, a trimmed clause, a fixed
    typo): `transform(fields) -> fields` edits the five stored fields of the active version; the row is
    inserted, activated through the audited switchboard and materialized like every other version.
    Returns None when the transform changes nothing."""
    from sqlalchemy import text
    from .compile import compile_effective
    from .model import FIELDS
    ctx = service._Ctx(engine, config_hash, repo_root, is_margin_account)
    active = ctx.current_version(agent_type)
    if active is None:
        raise SystemExit(f"{agent_type}: no active version for {config_hash}")
    row = ctx.row(agent_type, active)
    v, _a, _b = service._ensure_and_read(ctx, agent_type, active, materialized_by=CREATED_BY)
    effective = compile_effective(v)
    fields = {f: (row.get(f) or effective.get(f) or "") for f in FIELDS}
    new_fields = transform(dict(fields))
    changed = [f for f in FIELDS if (new_fields.get(f) or "") != (fields.get(f) or "")]
    if not changed:
        log(f"↷ {agent_type} v{active}: maintenance transform changes nothing — skipping")
        return None
    log(f"\n=== {agent_type} v{active} → maintenance version ({', '.join(changed)}) ===")
    for f in changed:
        log(f"  [{f}] {len(fields.get(f) or '')} → {len(new_fields.get(f) or '')} chars")
    if dry_run:
        return None
    with engine.begin() as conn:
        new_version = int(conn.execute(text("""
            SELECT COALESCE(MAX(version), -1) + 1 FROM prompt_versions WHERE agent_type = :a AND config_hash = :h
        """), {"a": agent_type, "h": config_hash}).scalar())
        desc = description.replace("{n}", str(new_version))
        new_id = int(conn.execute(text("""
            INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template, strategy_directives,
                soul, memory, description, created_by, is_active, config_hash)
            VALUES (:a, :v, :sp, :up, :sd, :soul, :mem, :d, :by, FALSE, :h) RETURNING id
        """), {"a": agent_type, "v": new_version, "sp": new_fields["system_prompt"], "up": new_fields["user_prompt_template"],
               "sd": new_fields["strategy_directives"], "soul": new_fields["soul"], "mem": new_fields["memory"],
               "d": desc, "by": CREATED_BY, "h": config_hash}).scalar())
        activate(conn, agent_type, config_hash, new_version, action="maintenance_version", actor=actor, reason=desc)
    mat = service.ensure_materialized(engine, config_hash, agent_type, new_version, repo_root=repo_root,
                                      is_margin_account=is_margin_account, materialized_by=CREATED_BY)
    log(f"  ✅ {agent_type} v{active} → v{new_version} (prompt_versions id {new_id}); latest/: {mat.get('latest')}")
    return {"version": new_version, "prompt_version_id": new_id, "changed": changed}


__all__ = ["apply_hand_authored", "maintenance_version", "CREATED_BY"]
