"""Train, evaluate and certify the policy router from the logs (read-only on the database).

    python -m policy_router.train --config-hash 9ea09b9as [--recall-target 0.98] [--routable entry,ltm]
           [--db-url postgresql:///] [--repo-root .] [--out-dir …] [--base-url http://127.0.0.1:1234/v1]

Protocol
  1. Rebuild every logged Decider cycle (dataset.py), oldest first, and label every candidate node
     (labels.py; theta from the explicit citation pairs).
  2. TIME SPLIT: the oldest ~70% of cycles train, the newest ~30% are held out.
  3. Settings (tau_min, the expected-recall target of the selection) are chosen by LEAVE-ONE-WEEK-OUT
     inside the training cycles only: the cheapest setting (fewest served chars) whose pooled
     out-of-fold recall meets the target. The held-out cycles are never used to choose.
  4. The model is fit on the training cycles and scored on the held-out cycles with those settings:
     recall overall and per node kind, served chars vs today's assembly, Brier, reliability bins,
     AUC, and the needed nodes the router would have missed. `certified` = held-out recall >= target.
  5. Leave-one-week-out over ALL cycles is reported as a second opinion.
  6. The artifact is refit on every cycle (priors included) with the chosen settings.

Priors are leak-free: inside a fit set the prior of a cycle uses only the cycles before it; scored
cycles use the frozen counts of the fit set (as at decision time). Writes only under --out-dir
(default <repo-root>/agents/decider/policy-router/<config_hash>/, gitignored). Never imports config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import DEFAULT_ROUTABLE, ROUTABLE_KINDS
from .dataset import CycleRecord, load_cycles
from .embed import DEFAULT_BASE_URL, DEFAULT_EMBED_MODEL, EmbedCache, EmbeddingClient
from .features import DOC_PREFIX, FEATURES, QUERY_PREFIX, Priors, feature_rows, texts_for, _logit
from .labels import label_node, theta_from_pairs
from .model import LogisticModel, auc, brier, expected_calibration_error, reliability
from .select import select_subgraph

SCHEMA = 1
PRIOR_IDX = FEATURES.index("prior_logit")
TAU_GRID = (0.5, 0.6, 0.7, 0.8, 0.9, 1.01)
TARGET_GRID = (0.5, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999, 1.0)
LABEL_DEFINITION = (
    "needed(node, cycle) = explicitly cited by a decision or considered setup of the cycle, OR the node text is "
    "reflected in one of the cycle's decision/considered reasons (max cosine(node, reason) >= theta; theta = a "
    "quantile of the cosine between explicitly cited guidelines and the reasons that cited them), OR the node "
    "names a ticker the cycle decided on or considered.")
LABEL_WEAKNESS = (
    "Similarity cannot tell use from redundancy: a memory row restating a pinned gate is labeled needed whenever "
    "the gate is applied; a ticker mention marks a node needed whenever the ticker is on the table. Both errors "
    "label more nodes needed, so recall against this label is conservative and savings are understated.")


def router_dir(repo_root: Path, config_hash: str, agent_dir: str = "decider") -> Path:
    return Path(repo_root) / "agents" / agent_dir / "policy-router" / config_hash


# ----------------------------------------------------------------------------- embeddings + labels
def embed_cycles(cycles: list, embedder, *, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX,
                 routable=DEFAULT_ROUTABLE) -> dict:
    """{text: unit vector} for every text the features and labels of these cycles need (one pass, cached):
    context chunks, candidate nodes, reasons, cited guidelines and the pinned guidelines."""
    texts: set = set()
    for c in cycles:
        texts.update(texts_for(c.ctx, c.nodes, query_prefix=query_prefix, doc_prefix=doc_prefix))
        texts.update(query_prefix + r for r in c.reasons)
        for _reason, ids in c.pairs:
            texts.update(doc_prefix + c.node_texts[i].strip() for i in ids if i in c.node_texts)
        texts.update(doc_prefix + c.node_texts[i].strip() for i in c.pinned_ids(routable))
    ordered = sorted(texts)
    vecs = embedder.embed(ordered, budget=None) if ordered else np.zeros((0, 0))
    return {t: vecs[i] for i, t in enumerate(ordered)}


def citation_similarities(cycles: list, vec: dict, *, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> list:
    sims = []
    for c in cycles:
        for reason, ids in c.pairs:
            rv = vec.get(query_prefix + reason)
            if rv is None:
                continue
            for i in ids:
                nv = vec.get(doc_prefix + c.node_texts.get(i, "").strip())
                if nv is not None and c.node_texts.get(i, "").strip():
                    sims.append(float(rv @ nv))
    return sims


LABEL_MODES = ("plain", "marginal")


def label_cycles(cycles: list, vec: dict, theta: float, *, mode: str = "plain", delta: float = 0.0,
                 routable=DEFAULT_ROUTABLE, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> dict:
    """{run_id: {node_id: (needed, why, max_sim)}}. mode "marginal" = the redundancy-aware variant."""
    if mode not in LABEL_MODES:
        raise ValueError(f"label mode must be one of {LABEL_MODES}")
    out = {}
    for c in cycles:
        rvecs = np.vstack([vec[query_prefix + r] for r in c.reasons]) if c.reasons else None
        best = None
        if mode == "marginal" and rvecs is not None:
            pins = [vec[doc_prefix + c.node_texts[i].strip()] for i in c.pinned_ids(routable)
                    if (doc_prefix + c.node_texts[i].strip()) in vec]
            best = (rvecs @ np.vstack(pins).T).max(axis=1) if pins else None
        lab = {}
        for n in c.nodes:
            lab[n.node_id] = label_node(n, cited=c.cited, node_vec=vec.get(doc_prefix + (n.text or "")),
                                        reason_vecs=rvecs, theta=theta, decided_tickers=c.decided_tickers,
                                        pinned_best=best, delta=delta)
        out[c.run_id] = lab
    return out


def base_features(cycles: list, vec: dict, *, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> dict:
    """{run_id: X} with a placeholder prior column (filled per protocol)."""
    flat = Priors()
    return {c.run_id: feature_rows(c.ctx, c.nodes, vec.__getitem__, flat, query_prefix=query_prefix,
                                   doc_prefix=doc_prefix) for c in cycles}


# ----------------------------------------------------------------------------- fit / predict
def fit_model(fit_cycles: list, X_by: dict, labels: dict, *, l2: float = 1.0, class_weight="balanced",
              strength: float = 4.0) -> tuple:
    """(model, priors after the fit set). Priors inside the fit set are expanding (no look-ahead)."""
    priors = Priors(strength=strength)
    Xs, ys = [], []
    for c in sorted(fit_cycles, key=lambda c: c.decided_at):
        X = X_by[c.run_id].copy()
        if len(X):
            X[:, PRIOR_IDX] = [_logit(priors.p(n.node_id, n.kind)) for n in c.nodes]
            Xs.append(X)
            ys.extend(1.0 if labels[c.run_id][n.node_id][0] else 0.0 for n in c.nodes)
        for n in c.nodes:
            priors.update(n.node_id, n.kind, labels[c.run_id][n.node_id][0])
    if not Xs:
        raise ValueError("no training rows")
    X = np.vstack(Xs)
    y = np.asarray(ys)
    if y.min() == y.max():
        raise ValueError("training labels have a single class")
    model = LogisticModel(l2=l2, class_weight=class_weight).fit(X, y, feature_names=FEATURES)
    return model, priors


def predict_cycles(model: LogisticModel, priors: Priors, cycles: list, X_by: dict) -> dict:
    out = {}
    for c in cycles:
        X = X_by[c.run_id].copy()
        if not len(X):
            out[c.run_id] = np.zeros(0)
            continue
        X[:, PRIOR_IDX] = [_logit(priors.p(n.node_id, n.kind)) for n in c.nodes]
        out[c.run_id] = model.predict_proba(X)
    return out


# ----------------------------------------------------------------------------- evaluation
def evaluate(cycles: list, p_by: dict, labels: dict, *, tau_min: float, recall_target: float, routable,
             ltm_cap: Optional[int] = 14, min_per_kind: Optional[dict] = None, keep_missed: bool = False) -> dict:
    routable = set(routable)
    need = sel_need = today_need = 0
    by_kind: dict = {}
    chars_sel = chars_today = chars_all = 0.0
    n_sel = n_today = n_all = 0
    missed = []
    ceiling = 0                    # needed nodes any ranking could keep under the memory cap
    for c in cycles:
        need_kind: dict = {}
        for n in c.nodes:
            if n.kind in routable and labels[c.run_id][n.node_id][0]:
                need_kind[n.kind] = need_kind.get(n.kind, 0) + 1
        ceiling += sum(min(v, ltm_cap) if (k == "ltm" and ltm_cap) else v for k, v in need_kind.items())
        p = p_by[c.run_id]
        items = [(n.node_id, n.kind, float(p[i]), n.chars) for i, n in enumerate(c.nodes) if n.kind in routable]
        sel = select_subgraph(items, tau_min=tau_min, recall_target=recall_target,
                              max_per_kind={"ltm": ltm_cap} if ltm_cap else None, min_per_kind=min_per_kind)
        inc = sel.include_ids
        for i, n in enumerate(c.nodes):
            if n.kind not in routable:
                continue
            needed, why, sim = labels[c.run_id][n.node_id]
            k = by_kind.setdefault(n.kind, {"needed": 0, "selected_needed": 0, "today_needed": 0,
                                            "nodes": 0, "selected": 0, "today": 0})
            k["nodes"] += 1
            k["selected"] += int(n.node_id in inc)
            k["today"] += int(n.node_id in c.today_ids)
            chars_all += n.chars
            n_all += 1
            if n.node_id in inc:
                chars_sel += n.chars
                n_sel += 1
            if n.node_id in c.today_ids:
                chars_today += n.chars
                n_today += 1
            if not needed:
                continue
            need += 1
            k["needed"] += 1
            if n.node_id in inc:
                sel_need += 1
                k["selected_needed"] += 1
            elif keep_missed:
                missed.append({"run_id": c.run_id, "node_id": n.node_id, "kind": n.kind, "p": round(float(p[i]), 4),
                               "why_needed": why, "max_sim": round(float(sim), 4),
                               "served_today": n.node_id in c.today_ids})
            if n.node_id in c.today_ids:
                today_need += 1
                k["today_needed"] += 1
    m = max(len(cycles), 1)
    for k in by_kind.values():
        k["recall"] = (k["selected_needed"] / k["needed"]) if k["needed"] else None
        k["today_recall"] = (k["today_needed"] / k["needed"]) if k["needed"] else None
    out = {"cycles": len(cycles), "needed": need, "recall": (sel_need / need) if need else None,
           "recall_ceiling": (ceiling / need) if need else None,
           "today_recall": (today_need / need) if need else None, "by_kind": by_kind,
           "chars_selected": chars_sel / m, "chars_today": chars_today / m, "chars_routable": chars_all / m,
           "nodes_selected": n_sel / m, "nodes_today": n_today / m, "nodes_routable": n_all / m,
           "chars_reduction_vs_today": (1 - chars_sel / chars_today) if chars_today else None}
    if keep_missed:
        out["missed"] = missed
    return out


def grid_search(cycles: list, p_by: dict, labels: dict, *, routable, ltm_cap, min_per_kind=None) -> list:
    rows = []
    for tau in TAU_GRID:
        for r in TARGET_GRID:
            ev = evaluate(cycles, p_by, labels, tau_min=tau, recall_target=r, routable=routable, ltm_cap=ltm_cap,
                          min_per_kind=min_per_kind)
            rows.append({"tau_min": tau, "recall_target": r, "recall": ev["recall"], "chars_selected": ev["chars_selected"],
                         "nodes_selected": ev["nodes_selected"]})
    return rows


def choose_setting(rows: list, target: float) -> tuple:
    """(setting, met): the cheapest setting whose recall >= target; else the highest-recall one."""
    ok = [r for r in rows if r["recall"] is not None and r["recall"] >= target - 1e-12]
    if ok:
        best = min(ok, key=lambda r: (r["chars_selected"], -r["recall"], -r["tau_min"]))
        return best, True
    scored = [r for r in rows if r["recall"] is not None]
    if not scored:
        return {"tau_min": 1.01, "recall_target": 1.0, "recall": None, "chars_selected": None}, False
    best = max(scored, key=lambda r: (r["recall"], -r["chars_selected"]))
    return best, False


def weeks_of(cycles: list) -> list:
    return sorted({c.week for c in cycles})


def lowo_predictions(cycles: list, X_by: dict, labels: dict, **fit_kw) -> tuple:
    """Out-of-fold p for every cycle (its ISO week held out). Returns (p_by, weeks_scored)."""
    p_by, scored = {}, []
    for w in weeks_of(cycles):
        held = [c for c in cycles if c.week == w]
        rest = [c for c in cycles if c.week != w]
        if not rest:
            continue
        try:
            model, priors = fit_model(rest, X_by, labels, **fit_kw)
        except ValueError:
            continue
        p_by.update(predict_cycles(model, priors, held, X_by))
        scored.append(w)
    return p_by, scored


def _flat(cycles, p_by, labels, routable) -> tuple:
    ps, ys = [], []
    for c in cycles:
        p = p_by.get(c.run_id)
        if p is None:
            continue
        for i, n in enumerate(c.nodes):
            if n.kind in routable:
                ps.append(float(p[i]))
                ys.append(1.0 if labels[c.run_id][n.node_id][0] else 0.0)
    return np.asarray(ps), np.asarray(ys)


def label_stats(cycles: list, labels: dict) -> dict:
    out: dict = {}
    for c in cycles:
        for n in c.nodes:
            needed, why, _sim = labels[c.run_id][n.node_id]
            k = out.setdefault(n.kind, {"rows": 0, "needed": 0, "explicit": 0, "similar": 0, "ticker": 0})
            k["rows"] += 1
            if needed:
                k["needed"] += 1
                k[why] += 1
    for k in out.values():
        k["needed_rate"] = k["needed"] / k["rows"] if k["rows"] else None
    return out


# ----------------------------------------------------------------------------- the whole run
def protocol(cycles: list, X_by: dict, labels: dict, *, recall_target: float, routable, train_frac: float,
             ltm_cap: Optional[int], fit_kw: dict, log: Callable = print) -> dict:
    """Time split + settings by leave-one-week-out on the training cycles + LOWO over all cycles."""
    cut = max(1, min(len(cycles) - 1, int(round(len(cycles) * float(train_frac)))))
    train, test = cycles[:cut], cycles[cut:]
    oof, weeks_scored = lowo_predictions(train, X_by, labels, **fit_kw)
    oof_cycles = [c for c in train if c.run_id in oof]
    if not oof_cycles:          # a single training week: fall back to a split inside the training cycles
        inner = max(1, int(len(train) * 0.7))
        m_in, pr_in = fit_model(train[:inner], X_by, labels, **fit_kw)
        oof = predict_cycles(m_in, pr_in, train[inner:], X_by)
        oof_cycles = train[inner:]
        weeks_scored = ["inner time split"]
    grid = grid_search(oof_cycles, oof, labels, routable=routable, ltm_cap=ltm_cap)
    setting, met_cv = choose_setting(grid, recall_target)
    log(f"🎛️  settings from leave-one-week-out on the training cycles: tau_min={setting['tau_min']} "
        f"expected-recall target={setting['recall_target']} (CV recall {setting['recall']}, met={met_cv})")
    model, priors = fit_model(train, X_by, labels, **fit_kw)
    p_test = predict_cycles(model, priors, test, X_by)
    held = evaluate(test, p_test, labels, tau_min=setting["tau_min"], recall_target=setting["recall_target"],
                    routable=routable, ltm_cap=ltm_cap, keep_missed=True)
    ps, ys = _flat(test, p_test, labels, routable)
    held.update({"brier": brier(ps, ys), "brier_base_rate": brier(np.full_like(ys, ys.mean() if len(ys) else 0), ys),
                 "ece": expected_calibration_error(ps, ys), "auc": auc(ps, ys), "reliability": reliability(ps, ys, 10),
                 "base_rate": float(ys.mean()) if len(ys) else None, "mean_p": float(ps.mean()) if len(ps) else None,
                 "first": test[0].decided_at.isoformat(), "last": test[-1].decided_at.isoformat()})
    held["grid"] = grid_search(test, p_test, labels, routable=routable, ltm_cap=ltm_cap)
    certified = bool(held["recall"] is not None and held["recall"] >= recall_target - 1e-12)
    oof_all, weeks_all = lowo_predictions(cycles, X_by, labels, **fit_kw)
    lowo_cycles = [c for c in cycles if c.run_id in oof_all]
    lowo = evaluate(lowo_cycles, oof_all, labels, tau_min=setting["tau_min"], recall_target=setting["recall_target"],
                    routable=routable, ltm_cap=ltm_cap) if lowo_cycles else {}
    if lowo_cycles:
        ps2, ys2 = _flat(lowo_cycles, oof_all, labels, routable)
        lowo.update({"brier": brier(ps2, ys2), "auc": auc(ps2, ys2), "weeks": weeks_all})
    return {"train": train, "test": test, "setting": setting, "met_cv": met_cv, "cv_weeks": weeks_scored,
            "cv_grid": grid, "heldout": held, "lowo": lowo, "certified": certified}


def _summary(res: dict) -> dict:
    h = res["heldout"]
    return {"setting": {k: res["setting"].get(k) for k in ("tau_min", "recall_target", "recall")},
            "certified": res["certified"], "lowo_recall": (res["lowo"] or {}).get("recall"),
            **{k: h.get(k) for k in ("recall", "recall_ceiling", "today_recall", "chars_selected", "chars_today", "chars_routable",
                                     "chars_reduction_vs_today", "nodes_selected", "nodes_today", "brier", "ece",
                                     "auc", "base_rate", "needed")},
            "by_kind": {k: {"recall": v["recall"], "today_recall": v["today_recall"], "needed": v["needed"]}
                        for k, v in (h.get("by_kind") or {}).items()},
            "missed": len(h.get("missed") or [])}


def run(cycles: list, embedder, *, config_hash: str, recall_target: float = 0.98, routable=DEFAULT_ROUTABLE,
        train_frac: float = 0.7, implicit_quantile: float = 0.5, theta: Optional[float] = None, l2: float = 1.0,
        ltm_cap: Optional[int] = 14, strength: float = 4.0, label_mode: str = "plain", delta: float = 0.0,
        compare_labels: bool = True, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX,
        log: Callable = print) -> tuple:
    """(artifact dict, report dict) from CycleRecords (oldest first)."""
    routable = tuple(k for k in routable if k in ROUTABLE_KINDS)
    cycles = sorted(cycles, key=lambda c: c.decided_at)
    if len(cycles) < 10:
        raise ValueError(f"only {len(cycles)} logged cycles — too few to train and hold out")
    t0 = time.monotonic()
    vec = embed_cycles(cycles, embedder, query_prefix=query_prefix, doc_prefix=doc_prefix, routable=routable)
    log(f"🧮 embedded {len(vec)} texts in {time.monotonic() - t0:.1f}s ({getattr(embedder, 'calls', '?')} requests)")
    sims = citation_similarities(cycles, vec, query_prefix=query_prefix, doc_prefix=doc_prefix)
    theta_used = float(theta) if theta is not None else theta_from_pairs(sims, implicit_quantile)
    lab_kw = dict(delta=delta, routable=routable, query_prefix=query_prefix, doc_prefix=doc_prefix)
    labels = label_cycles(cycles, vec, theta_used, mode=label_mode, **lab_kw)
    X_by = base_features(cycles, vec, query_prefix=query_prefix, doc_prefix=doc_prefix)
    fit_kw = {"l2": l2, "strength": strength}
    pkw = dict(recall_target=recall_target, routable=routable, train_frac=train_frac, ltm_cap=ltm_cap, fit_kw=fit_kw)
    res = protocol(cycles, X_by, labels, log=log, **pkw)
    setting, held, lowo, certified = res["setting"], res["heldout"], res["lowo"], res["certified"]
    alternatives = {}
    if compare_labels:
        for mode in LABEL_MODES:
            if mode == label_mode:
                continue
            try:
                alt_labels = label_cycles(cycles, vec, theta_used, mode=mode, **lab_kw)
                alt = protocol(cycles, X_by, alt_labels, log=lambda *_a, **_k: None, **pkw)
                alternatives[mode] = dict(_summary(alt), label_stats=label_stats(cycles, alt_labels))
            except ValueError as exc:
                alternatives[mode] = {"error": str(exc)}

    # the artifact: refit on every cycle
    final_model, final_priors = fit_model(cycles, X_by, labels, **fit_kw)
    trained_at = datetime.now().isoformat(timespec="seconds")
    body = json.dumps(final_model.to_dict(), sort_keys=True) + json.dumps(final_priors.to_dict(), sort_keys=True)
    model_version = hashlib.sha256((body + trained_at).encode("utf-8")).hexdigest()[:12]
    certification = {
        "target": float(recall_target), "certified": certified, "heldout_recall": held["recall"],
        "heldout_cycles": len(res["test"]), "train_cycles": len(res["train"]),
        "protocol": f"time split {int(round(train_frac * 100))}/{100 - int(round(train_frac * 100))} "
                    f"(settings by leave-one-week-out on the training cycles)",
        "lowo_recall": lowo.get("recall"), "cv_recall": setting.get("recall"), "cv_met": res["met_cv"],
        "routable": list(routable), "ltm_cap": ltm_cap, "label_mode": label_mode,
    }
    label_meta = {"mode": label_mode, "delta": delta if label_mode == "marginal" else None, "theta": theta_used,
                  "quantile": implicit_quantile if theta is None else None,
                  "definition": LABEL_DEFINITION, "weakness": LABEL_WEAKNESS}
    artifact = {
        "schema": SCHEMA, "kind": "policy_router", "agent_type": "DeciderAgent", "config_hash": config_hash,
        "model_version": model_version, "trained_at": trained_at, "cycles": len(cycles),
        "embed": {"base_url": getattr(embedder, "base_url", ""), "model": getattr(embedder, "model", ""),
                  "query_prefix": query_prefix, "doc_prefix": doc_prefix},
        "features": list(FEATURES), "model": final_model.to_dict(), "priors": final_priors.to_dict(),
        "label": label_meta,
        "selection": {"tau_min": setting["tau_min"], "recall_target": setting["recall_target"],
                      "min_per_kind": {}, "max_per_kind": {"ltm": ltm_cap} if ltm_cap else {}},
        "routable": list(routable), "certification": certification, "certified": certified,
        "heldout": {k: held.get(k) for k in ("recall", "recall_ceiling", "today_recall", "brier", "ece", "auc", "chars_selected",
                                               "chars_today", "chars_routable", "chars_reduction_vs_today",
                                               "nodes_selected", "nodes_today", "nodes_routable", "cycles", "needed")},
        "alternatives": alternatives,
    }
    coef = dict(zip(FEATURES, [round(float(x), 4) for x in final_model.coef_]))
    report = {
        "config_hash": config_hash, "trained_at": trained_at, "model_version": model_version,
        "cycles": len(cycles), "first": cycles[0].decided_at.isoformat(), "last": cycles[-1].decided_at.isoformat(),
        "weeks": weeks_of(cycles), "routable": list(routable), "recall_target": recall_target,
        "label": dict(label_meta, citation_pairs=len(sims),
                      citation_sim_quantiles=({q: float(np.quantile(sims, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
                                              if sims else {}),
                      stats=label_stats(cycles, labels)),
        "context_sources": _source_counts(cycles),
        "setting": setting, "cv_weeks": res["cv_weeks"], "cv_grid": res["cv_grid"],
        "heldout": held, "lowo_all": lowo, "certification": certification, "alternatives": alternatives,
        "coefficients_standardized": coef,
    }
    return artifact, report


def _source_counts(cycles: list) -> dict:
    out: dict = {}
    for c in cycles:
        for k, v in (c.source or {}).items():
            d = out.setdefault(k, {})
            d[str(v)] = d.get(str(v), 0) + 1
    return out


# ----------------------------------------------------------------------------- report (markdown)
def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def report_markdown(report: dict) -> str:
    h = report["heldout"]
    c = report["certification"]
    L = report["label"]
    lines = [
        f"# Policy router — evaluation ({report['config_hash']})",
        "",
        f"Trained {report['trained_at']} on {report['cycles']} Decider cycles ({report['first'][:10]} → {report['last'][:10]}, "
        f"weeks {', '.join(report['weeks'])}). Routable kinds: {', '.join(report['routable'])}. Label: {L.get('mode', 'plain')}. "
        f"Model {report['model_version']}.",
        "",
        "## Verdict",
        "",
        f"- Held-out recall (newest {h['cycles']} cycles, {h['first'][:10]} → {h['last'][:10]}): **{_pct(h['recall'])}** "
        f"vs target {_pct(c['target'])} → **{'CERTIFIED' if c['certified'] else 'NOT certified'}**.",
        f"- Today's assembly on the same cycles: recall {_pct(h['today_recall'])}. Best recall any ranking could reach "
        f"under the memory cap: {_pct(h.get('recall_ceiling'))}.",
        f"- Served routable chars per cycle: router {h['chars_selected']:.0f} vs today {h['chars_today']:.0f} "
        f"(all routable {h['chars_routable']:.0f}) → reduction vs today {_pct(h['chars_reduction_vs_today'])}.",
        f"- Nodes per cycle: router {h['nodes_selected']:.1f} vs today {h['nodes_today']:.1f} of {h['nodes_routable']:.1f}.",
        f"- Brier {h['brier']:.4f} (base-rate forecast {h['brier_base_rate']:.4f}), ECE {h['ece']:.4f}, AUC "
        f"{(h['auc'] if h['auc'] is not None else float('nan')):.3f}; base rate {_pct(h['base_rate'])}, mean p {_pct(h['mean_p'])}.",
        f"- Leave-one-week-out over all cycles: recall {_pct((report.get('lowo_all') or {}).get('recall'))}.",
        f"- Settings (chosen by leave-one-week-out on the training cycles, CV recall {_pct(report['setting'].get('recall'))}): "
        f"tau_min {report['setting']['tau_min']}, expected-recall target {report['setting']['recall_target']}.",
        "",
        "## Recall by kind (held out)",
        "",
        "| kind | nodes/cycle | needed | router recall | today recall | router keeps/cycle | today keeps/cycle |",
        "|---|---|---|---|---|---|---|",
    ]
    for kind, k in sorted(h["by_kind"].items()):
        n = max(h["cycles"], 1)
        lines.append(f"| {kind} | {k['nodes'] / n:.1f} | {k['needed']} | {_pct(k['recall'])} | {_pct(k['today_recall'])} | "
                     f"{k['selected'] / n:.1f} | {k['today'] / n:.1f} |")
    alts = report.get("alternatives") or {}
    if alts:
        lines += ["", "## The same protocol under the other label", "",
                  "| label | held-out recall | today recall | router chars | today chars | reduction | Brier | certified |",
                  "|---|---|---|---|---|---|---|---|"]
        for mode, a in alts.items():
            if a.get("error"):
                lines.append(f"| {mode} | error: {a['error']} | | | | | | |")
                continue
            lines.append(f"| {mode} | {_pct(a['recall'])} | {_pct(a['today_recall'])} | {a['chars_selected']:.0f} | "
                         f"{a['chars_today']:.0f} | {_pct(a['chars_reduction_vs_today'])} | {a['brier']:.4f} | "
                         f"{'yes' if a['certified'] else 'no'} |")
    lines += ["", "## Label", "", L["definition"], "", f"Weakness: {L['weakness']}", "",
              f"theta = {L['theta']:.4f} (quantile {L['quantile']} of {L['citation_pairs']} cited guideline ↔ citing reason "
              f"cosines; quantiles {', '.join(f'{k}: {v:.3f}' for k, v in L['citation_sim_quantiles'].items())}).", "",
              "| kind | rows | needed | rate | explicit | similar | ticker |", "|---|---|---|---|---|---|---|"]
    for kind, s in sorted(L["stats"].items()):
        lines.append(f"| {kind} | {s['rows']} | {s['needed']} | {_pct(s['needed_rate'])} | {s['explicit']} | {s['similar']} | {s['ticker']} |")
    lines += ["", "## Reliability (held out)", "", "| p bin | n | mean p | observed |", "|---|---|---|---|"]
    for b in h["reliability"]:
        lines.append(f"| {b['lo']:.1f}–{b['hi']:.1f} | {b['n']} | {b['mean_p']:.3f} | {b['frac_pos']:.3f} |")
    missed = h.get("missed") or []
    lines += ["", f"## Needed nodes the router would have missed ({len(missed)})", ""]
    if missed:
        agg: dict = {}
        for m in missed:
            a = agg.setdefault(m["node_id"], {"n": 0, "why": {}, "p": [], "today": 0})
            a["n"] += 1
            a["why"][m["why_needed"]] = a["why"].get(m["why_needed"], 0) + 1
            a["p"].append(m["p"])
            a["today"] += int(m["served_today"])
        lines += ["| node | times | needed because | mean p | served by today's prompt |", "|---|---|---|---|---|"]
        for nid, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"| {nid} | {a['n']} | {', '.join(f'{k} {v}' for k, v in a['why'].items())} | "
                         f"{sum(a['p']) / len(a['p']):.3f} | {a['today']} of {a['n']} |")
    else:
        lines.append("None.")
    lines += ["", "## Context sources", "", "```", json.dumps(report.get("context_sources") or {}, indent=1), "```",
              "", "## Standardized coefficients", "", "```", json.dumps(report["coefficients_standardized"], indent=1), "```", ""]
    return "\n".join(lines)


def write_outputs(out_dir: Path, artifact: dict, report: dict) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"artifact": out_dir / "model.json", "report_json": out_dir / "eval.json", "report_md": out_dir / "eval.md"}
    for key, path in paths.items():
        tmp = path.with_suffix(path.suffix + ".part")
        if key == "report_md":
            tmp.write_text(report_markdown(report), encoding="utf-8")
        else:
            tmp.write_text(json.dumps(artifact if key == "artifact" else report, indent=1, default=str), encoding="utf-8")
        tmp.replace(path)
    return paths


# ----------------------------------------------------------------------------- CLI
def _engine(db_url: str):
    from sqlalchemy import create_engine
    if db_url.startswith("postgresql"):
        return create_engine(db_url, connect_args={"options": "-c default_transaction_read_only=on"})
    return create_engine(db_url)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m policy_router.train", description=__doc__.split("\n\n")[0])
    p.add_argument("--config-hash", required=True)
    p.add_argument("--recall-target", type=float, default=0.98)
    p.add_argument("--routable", default=",".join(DEFAULT_ROUTABLE), help="node kinds the router may drop (entry,ltm[,lesson])")
    p.add_argument("--db-url", default="postgresql:///", help="SQLAlchemy URL (opened read-only for Postgres)")
    p.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent),
                   help="repo root holding agents/decider/policy-graph/<hash>/")
    p.add_argument("--out-dir", default=None, help="default <repo-root>/agents/decider/policy-router/<hash>/")
    p.add_argument("--cache", default=None, help="embedding cache file (default <out-dir>/../embed-cache.sqlite3)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--implicit-quantile", type=float, default=0.5)
    p.add_argument("--theta", type=float, default=None, help="fixed similarity threshold (overrides the quantile)")
    p.add_argument("--l2", type=float, default=1.0)
    p.add_argument("--ltm-cap", type=int, default=14, help="upper bound on memory rows served (DAI_MEMORY_LT_LIMIT)")
    p.add_argument("--limit", type=int, default=None, help="only the newest N cycles")
    p.add_argument("--label", choices=LABEL_MODES, default="plain",
                   help="plain = explicit | similar | ticker; marginal = similar only where the node beats every pinned guideline")
    p.add_argument("--delta", type=float, default=0.0, help="marginal label: tolerance below the best pinned cosine")
    p.add_argument("--no-compare", action="store_true", help="skip evaluating the other label mode")
    args = p.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir) if args.out_dir else router_dir(repo_root, args.config_hash)
    cache_path = Path(args.cache) if args.cache else out_dir.parent / "embed-cache.sqlite3"
    routable = tuple(k.strip() for k in args.routable.split(",") if k.strip())
    bad = [k for k in routable if k not in ROUTABLE_KINDS]
    if bad:
        print(f"unknown routable kind(s): {', '.join(bad)} (allowed: {', '.join(ROUTABLE_KINDS)})", file=sys.stderr)
        return 2
    engine = _engine(args.db_url)
    store_root = repo_root / "agents" / "decider" / "policy-graph" / args.config_hash
    cycles = load_cycles(engine, args.config_hash, store_root=store_root, limit=args.limit)
    print(f"📚 {len(cycles)} logged Decider cycles rebuilt from {args.db_url} + {store_root}")
    embedder = EmbeddingClient(args.base_url, args.embed_model, cache=EmbedCache(cache_path), timeout=60.0)
    artifact, report = run(cycles, embedder, config_hash=args.config_hash, recall_target=args.recall_target,
                           routable=routable, train_frac=args.train_frac, implicit_quantile=args.implicit_quantile,
                           theta=args.theta, l2=args.l2, ltm_cap=args.ltm_cap, label_mode=args.label,
                           delta=args.delta, compare_labels=not args.no_compare)
    paths = write_outputs(out_dir, artifact, report)
    h = report["heldout"]
    print(f"✅ held-out recall {_pct(h['recall'])} (target {_pct(args.recall_target)}) → "
          f"{'CERTIFIED' if artifact['certified'] else 'NOT certified'}; today {_pct(h['today_recall'])}; "
          f"chars/cycle router {h['chars_selected']:.0f} vs today {h['chars_today']:.0f}; Brier {h['brier']:.4f}; "
          f"missed {len(h.get('missed') or [])}")
    for k, v in paths.items():
        print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
