"""The Policy Graph tab's Router panel: mode, certification, served chars vs today, the last cycle's per-node
p, and the shadow recall of explicit citations over the last N cycles. Plain-language notes included."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .runtime import artifact_path, load_artifact


def _note(mode: Optional[str], effective: Optional[str], certified: Optional[bool], has_artifact: bool) -> str:
    if not has_artifact and not mode:
        return ("The router has no trained model yet and has not run. Train it with "
                "`python -m policy_router.train --config-hash <hash>`; until then the Decider reads today's prompt.")
    if effective == "active":
        return ("Active: the Decider reads the pinned policy plus the diary entries and memory rows the router "
                "kept; the rest are listed by id so they stay citable.")
    if effective == "fallback":
        return "The last cycle fell back to today's prompt (see the note). Nothing was routed."
    if mode == "active" and effective == "shadow":
        return "Active was requested but the model is not certified for these settings, so it runs in shadow."
    return ("Shadow: every cycle the router scores each diary entry and memory row and logs what it would keep, "
            "but the Decider still reads exactly today's prompt.")


def router_panel(engine, config_hash: str, *, repo_root, last_n: int = 30) -> dict:
    from . import log as rlog
    out: dict = {"config_hash": config_hash, "artifact": None, "mode": None, "effective_mode": None,
                 "last_cycle": None, "shadow": None, "runs": [], "note": ""}
    path = artifact_path(Path(repo_root), config_hash)
    try:
        art = load_artifact(path)
    except Exception as exc:     # noqa: BLE001
        art = None
        out["artifact_error"] = f"{type(exc).__name__}: {exc}"
    if art:
        cert = art.get("certification") or {}
        h = art.get("heldout") or {}
        out["artifact"] = {
            "model_version": art.get("model_version"), "trained_at": art.get("trained_at"), "cycles": art.get("cycles"),
            "certified": bool(art.get("certified")), "target": cert.get("target"),
            "heldout_recall": cert.get("heldout_recall"), "lowo_recall": cert.get("lowo_recall"),
            "today_recall": h.get("today_recall"), "recall_ceiling": h.get("recall_ceiling"),
            "chars_selected": h.get("chars_selected"), "chars_today": h.get("chars_today"),
            "chars_routable": h.get("chars_routable"), "chars_reduction_vs_today": h.get("chars_reduction_vs_today"),
            "brier": h.get("brier"), "auc": h.get("auc"), "routable": art.get("routable"),
            "label_mode": (art.get("label") or {}).get("mode"), "protocol": cert.get("protocol"),
            "heldout_cycles": cert.get("heldout_cycles"),
        }
    try:
        runs = rlog.recent_runs(engine, config_hash, limit=last_n)
    except Exception:            # noqa: BLE001 — table not created yet
        runs = []
    out["runs"] = runs
    if runs:
        last = runs[0]
        out["mode"] = last.get("mode")
        out["effective_mode"] = last.get("effective_mode")
        nodes = []
        try:
            nodes = rlog.run_decisions(engine, config_hash, last["run_id"]) if last.get("run_id") else []
        except Exception:        # noqa: BLE001
            nodes = []
        out["last_cycle"] = dict(last, nodes=nodes)
        try:
            out["shadow"] = rlog.shadow_recall(engine, config_hash, last_n=last_n)
        except Exception:        # noqa: BLE001
            out["shadow"] = None
    out["note"] = _note(out["mode"], out["effective_mode"], (out["artifact"] or {}).get("certified"), bool(art))
    return out


__all__ = ["router_panel"]
