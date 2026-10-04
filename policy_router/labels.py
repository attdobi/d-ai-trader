"""What "needed" means: needed(node, cycle) = explicit OR similar OR ticker.

    explicit  a decision of the cycle cited the node's id (` [cites: …]` / the hit log), or a considered
              (rejected / held) setup did — read when the decisions carry such citations
    similar   the node's text is reflected in one of the cycle's decision or considered reasons:
              max cosine(node, reason) >= theta
    ticker    the node names a ticker the cycle decided on or considered

theta comes from the data (`theta_from_pairs`): a quantile (default the median) of the cosine between
each explicitly cited guideline and the reason that cited it — "a reason reflects this node at least as
strongly as a typical explicit citation reflects its guideline".

Weakness (see the package docstring): similarity cannot separate use from redundancy (a memory row that
restates a pinned gate is labeled needed whenever the gate is applied), and a ticker mention marks a node
needed whenever its ticker is on the table. Both errors label MORE nodes needed, never fewer.

Variant "marginal" (train --label marginal): the similar clause also requires that the node explains the
reason at least as well as every pinned guideline (gates, rules, sections, soul, code blocks) does, minus
`delta` — "the node carried something the always-served prompt did not". It removes the redundancy error
but can under-label a node that restates a gate with one decisive nuance worded like the gate.
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

import numpy as np

from policy_graph.citations import normalize_ids, parse_cites, strip_cites

SKIP_TICKERS = {"CASH", "PORTFOLIO", "N/A", ""}


def _items(data) -> list:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if isinstance(data, dict):
        out = list(data.get("decisions") or [])
        if isinstance(data.get("considered"), list):
            out.append({"kind": "considered_audit", "considered": data["considered"]})
        return out
    return list(data or [])


def parse_decisions(payloads: Iterable) -> dict:
    """From one cycle's `trade_decisions.data` payloads:
    reasons   [text] — every decision reason and considered "why" (citation suffix stripped)
    pairs     [(text, [ids])] — reasons that carry explicit citations
    cited     {ids} — every id cited by a decision or a considered setup
    tickers   {tickers} decided on or considered
    holdings  {tickers} the cycle held / sold (decisions only)
    """
    reasons, pairs, cited, tickers, holdings = [], [], set(), set(), set()
    considered_cites = 0
    for data in payloads or []:
        for d in _items(data):
            if not isinstance(d, dict):
                continue
            if d.get("kind") == "considered_audit" or (isinstance(d.get("considered"), list) and not d.get("action")):
                for c in d.get("considered") or []:
                    if not isinstance(c, dict):
                        continue
                    raw = str(c.get("why") or c.get("reason") or "")
                    ids = parse_cites(raw)
                    for extra in (c.get("cited"), c.get("cites"), c.get("guidelines")):
                        ids += [i for i in normalize_ids(extra) if i not in ids]
                    text = strip_cites(raw).strip()
                    if text:
                        reasons.append(text)
                        if ids:
                            pairs.append((text, ids))
                    if ids:
                        considered_cites += 1
                    cited |= set(ids)
                    tk = str(c.get("ticker") or "").upper().strip()
                    if tk not in SKIP_TICKERS:
                        tickers.add(tk)
                continue
            action = str(d.get("action") or "").lower()
            if action not in ("buy", "sell", "hold"):
                continue
            raw = str(d.get("reason") or "")
            ids = parse_cites(raw)
            ids += [i for i in normalize_ids(d.get("cited")) if i not in ids]
            text = strip_cites(raw).strip()
            if text:
                reasons.append(text)
                if ids:
                    pairs.append((text, ids))
            cited |= set(ids)
            tk = str(d.get("ticker") or "").upper().strip()
            if tk not in SKIP_TICKERS:
                tickers.add(tk)
                if action in ("hold", "sell"):
                    holdings.add(tk)
    return {"reasons": list(dict.fromkeys(reasons)), "pairs": pairs, "cited": cited, "tickers": tickers,
            "holdings": holdings, "considered_cites": considered_cites}


def theta_from_pairs(sims: Iterable, quantile: float = 0.5, default: float = 0.6) -> float:
    vals = np.asarray([float(s) for s in sims], dtype=np.float64)
    if not len(vals):
        return float(default)
    return float(np.quantile(vals, min(max(float(quantile), 0.0), 1.0)))


def label_node(node, *, cited: set, node_vec: Optional[np.ndarray], reason_vecs: Optional[np.ndarray], theta: float,
               decided_tickers: set, pinned_best: Optional[np.ndarray] = None, delta: float = 0.0) -> tuple:
    """(needed, why, max_sim) — why in explicit | similar | ticker | ''.

    `pinned_best` (one value per reason: the best cosine any PINNED guideline reaches on that reason) turns
    on the redundancy-aware ("marginal") variant: a reason counts only when this node explains it at least
    as well as everything that is always served (cosine(node, reason) >= pinned_best - delta)."""
    sim = 0.0
    hit = False
    if node_vec is not None and reason_vecs is not None and len(reason_vecs):
        sims = reason_vecs @ node_vec
        sim = float(sims.max())
        ok = sims >= theta
        if pinned_best is not None and len(pinned_best) == len(sims):
            ok = ok & ((sims - pinned_best) >= -float(delta))
        hit = bool(ok.any())
    if node.node_id in cited:
        return True, "explicit", sim
    if hit:
        return True, "similar", sim
    if set(node.tickers) & set(decided_tickers or ()):
        return True, "ticker", sim
    return False, "", sim


__all__ = ["parse_decisions", "theta_from_pairs", "label_node"]
