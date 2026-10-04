"""L2-regularized logistic regression in numpy (IRLS / Newton), with class weighting that keeps p calibrated.

    m = LogisticModel(l2=1.0, class_weight="balanced").fit(X, y)
    p = m.predict_proba(X)                       # calibrated P(needed)
    LogisticModel.from_dict(m.to_dict())          # JSON round trip

Features are standardized inside the model (mean/std stored). Class weighting (positives are the
minority for most node kinds) moves the decision boundary but also shifts the intercept by about
log(w_pos / w_neg); `prior_correction` subtracts that shift after fitting, so predicted
probabilities stay on the scale of the true base rate (King & Zeng's prior correction).
The intercept is not penalized. No sklearn.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


def _sigmoid(z):
    z = np.clip(z, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-z))


class LogisticModel:
    def __init__(self, l2: float = 1.0, class_weight=None, *, max_iter: int = 100, tol: float = 1e-8,
                 prior_correction: bool = True):
        self.l2 = float(l2)
        self.class_weight = class_weight
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.prior_correction = bool(prior_correction)
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None
        self.coef_: Optional[np.ndarray] = None
        self.intercept_: float = 0.0
        self.correction_: float = 0.0
        self.n_iter_: int = 0
        self.feature_names: list = []

    # ------------------------------------------------------------------ fit
    def _weights(self, y: np.ndarray) -> tuple:
        pos = float(y.sum())
        neg = float(len(y) - pos)
        cw = self.class_weight
        if cw == "balanced" and pos > 0 and neg > 0:
            w1, w0 = len(y) / (2.0 * pos), len(y) / (2.0 * neg)
        elif isinstance(cw, dict):
            w1, w0 = float(cw.get(1, 1.0)), float(cw.get(0, 1.0))
        else:
            w1 = w0 = 1.0
        return w1, w0

    def fit(self, X, y, sample_weight=None, feature_names: Optional[Sequence[str]] = None) -> "LogisticModel":
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64).ravel()
        if X.ndim != 2 or len(X) != len(y):
            raise ValueError("X must be (n, d) and y (n,)")
        self.feature_names = list(feature_names or [])
        self.mean_ = X.mean(axis=0) if len(X) else np.zeros(X.shape[1])
        std = X.std(axis=0) if len(X) else np.ones(X.shape[1])
        std[std < 1e-9] = 1.0
        self.std_ = std
        Z = (X - self.mean_) / self.std_
        n, d = Z.shape
        A = np.hstack([np.ones((n, 1)), Z])
        w1, w0 = self._weights(y)
        w = np.where(y > 0.5, w1, w0)
        if sample_weight is not None:
            w = w * np.asarray(sample_weight, dtype=np.float64).ravel()
        pen = np.full(d + 1, self.l2)
        pen[0] = 0.0
        beta = np.zeros(d + 1)
        base = float(np.clip((w * y).sum() / max(w.sum(), 1e-12), 1e-6, 1 - 1e-6))
        beta[0] = math.log(base / (1 - base))
        for it in range(self.max_iter):
            p = _sigmoid(A @ beta)
            s = np.maximum(p * (1 - p), 1e-10) * w
            grad = A.T @ (w * (p - y)) + pen * beta
            H = (A * s[:, None]).T @ A + np.diag(pen + 1e-9)
            try:
                step = np.linalg.solve(H, grad)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(H, grad, rcond=None)[0]
            beta = beta - step
            self.n_iter_ = it + 1
            if float(np.max(np.abs(step))) < self.tol:
                break
        self.intercept_ = float(beta[0])
        self.coef_ = beta[1:].copy()
        self.correction_ = math.log(w1 / w0) if (self.prior_correction and w1 > 0 and w0 > 0) else 0.0
        return self

    # ------------------------------------------------------------------ predict
    def decision_function(self, X) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("model is not fitted")
        X = np.asarray(X, dtype=np.float64)
        Z = (X - self.mean_) / self.std_
        return Z @ self.coef_ + self.intercept_ - self.correction_

    def predict_proba(self, X) -> np.ndarray:
        return _sigmoid(self.decision_function(X))

    # ------------------------------------------------------------------ serialization
    def to_dict(self) -> dict:
        return {"kind": "logistic_l2_irls", "l2": self.l2,
                "class_weight": self.class_weight if not isinstance(self.class_weight, dict)
                else {str(k): v for k, v in self.class_weight.items()},
                "prior_correction": self.prior_correction, "feature_names": list(self.feature_names),
                "mean": [float(x) for x in self.mean_], "std": [float(x) for x in self.std_],
                "coef": [float(x) for x in self.coef_], "intercept": float(self.intercept_),
                "correction": float(self.correction_), "n_iter": int(self.n_iter_)}

    @classmethod
    def from_dict(cls, d: dict) -> "LogisticModel":
        cw = d.get("class_weight")
        if isinstance(cw, dict):
            cw = {int(k): float(v) for k, v in cw.items()}
        m = cls(l2=d.get("l2", 1.0), class_weight=cw, prior_correction=d.get("prior_correction", True))
        m.feature_names = list(d.get("feature_names") or [])
        m.mean_ = np.asarray(d["mean"], dtype=np.float64)
        m.std_ = np.asarray(d["std"], dtype=np.float64)
        m.coef_ = np.asarray(d["coef"], dtype=np.float64)
        m.intercept_ = float(d["intercept"])
        m.correction_ = float(d.get("correction", 0.0))
        m.n_iter_ = int(d.get("n_iter", 0))
        if len(m.coef_) != len(m.mean_):
            raise ValueError("model artifact is inconsistent (coef vs mean length)")
        return m


# ----------------------------------------------------------------------------- calibration
def brier(p, y) -> Optional[float]:
    p = np.asarray(p, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    if not len(p):
        return None
    return float(np.mean((p - y) ** 2))


def reliability(p, y, bins: int = 10) -> list:
    """[{lo, hi, n, mean_p, frac_pos}] over equal-width probability bins (empty bins omitted)."""
    p = np.asarray(p, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    out = []
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    for i in range(int(bins)):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        if not m.any():
            continue
        out.append({"lo": round(float(lo), 3), "hi": round(float(hi), 3), "n": int(m.sum()),
                    "mean_p": float(p[m].mean()), "frac_pos": float(y[m].mean())})
    return out


def expected_calibration_error(p, y, bins: int = 10) -> Optional[float]:
    rows = reliability(p, y, bins)
    n = sum(r["n"] for r in rows)
    if not n:
        return None
    return float(sum(r["n"] * abs(r["mean_p"] - r["frac_pos"]) for r in rows) / n)


def auc(p, y) -> Optional[float]:
    """Area under the ROC curve (rank statistic, ties averaged); None without both classes."""
    p = np.asarray(p, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    pos, neg = int((y > 0.5).sum()), int((y <= 0.5).sum())
    if not pos or not neg:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = p[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y > 0.5].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


__all__ = ["LogisticModel", "brier", "reliability", "expected_calibration_error", "auc"]
