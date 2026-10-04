"""policy_router.model: L2 logistic regression (IRLS) — separable data, calibration, class weighting with prior
correction, JSON round trip, and the calibration metrics."""
from __future__ import annotations

import json

import numpy as np
import pytest

from policy_router.model import LogisticModel, auc, brier, expected_calibration_error, reliability


def test_separable_toy_data_is_classified_and_stays_finite():
    rng = np.random.default_rng(0)
    X0 = rng.normal(-2.0, 0.5, size=(60, 2))
    X1 = rng.normal(2.0, 0.5, size=(60, 2))
    X = np.vstack([X0, X1])
    y = np.r_[np.zeros(60), np.ones(60)]
    m = LogisticModel(l2=0.1).fit(X, y)
    p = m.predict_proba(X)
    assert np.all(np.isfinite(m.coef_)) and np.isfinite(m.intercept_)      # L2 keeps separable data bounded
    assert ((p > 0.5) == (y > 0.5)).all()
    assert p[:60].max() < 0.2 and p[60:].min() > 0.8
    assert auc(p, y) == pytest.approx(1.0)


def test_calibration_on_data_drawn_from_a_logistic_model():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(6000, 3))
    true_logit = 1.2 * X[:, 0] - 0.8 * X[:, 1] - 0.5
    y = (rng.random(6000) < 1 / (1 + np.exp(-true_logit))).astype(float)
    m = LogisticModel(l2=0.01).fit(X, y)
    p = m.predict_proba(X)
    assert m.coef_[0] > 1.0 and m.coef_[1] < -0.6 and abs(m.coef_[2]) < 0.1
    assert abs(p.mean() - y.mean()) < 0.01
    for b in reliability(p, y, 10):
        if b["n"] >= 200:
            assert abs(b["mean_p"] - b["frac_pos"]) < 0.06
    assert expected_calibration_error(p, y) < 0.03
    assert brier(p, y) < brier(np.full_like(y, y.mean()), y)               # better than the base-rate forecast


def test_class_weighting_with_prior_correction_keeps_the_base_rate():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(4000, 2))
    logit = 1.5 * X[:, 0] - 2.5                                              # rare positives (~12%)
    y = (rng.random(4000) < 1 / (1 + np.exp(-logit))).astype(float)
    corrected = LogisticModel(l2=0.01, class_weight="balanced").fit(X, y)
    raw = LogisticModel(l2=0.01, class_weight="balanced", prior_correction=False).fit(X, y)
    assert corrected.correction_ == pytest.approx(np.log((len(y) - y.sum()) / y.sum()), rel=1e-6)
    assert abs(corrected.predict_proba(X).mean() - y.mean()) < 0.03
    assert raw.predict_proba(X).mean() > y.mean() + 0.15                     # uncorrected weighting inflates p
    # same ranking either way
    assert auc(corrected.predict_proba(X), y) == pytest.approx(auc(raw.predict_proba(X), y))


def test_json_round_trip_and_inconsistent_artifact():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(200, 4))
    y = (X[:, 0] + rng.normal(scale=0.5, size=200) > 0).astype(float)
    m = LogisticModel(l2=0.5, class_weight={1: 2.0, 0: 1.0}).fit(X, y, feature_names=["a", "b", "c", "d"])
    d = json.loads(json.dumps(m.to_dict()))
    m2 = LogisticModel.from_dict(d)
    assert m2.feature_names == ["a", "b", "c", "d"]
    np.testing.assert_allclose(m2.predict_proba(X), m.predict_proba(X))
    d["coef"] = d["coef"][:2]
    with pytest.raises(ValueError):
        LogisticModel.from_dict(d)


def test_fit_validates_shapes_and_unfitted_predict_raises():
    with pytest.raises(ValueError):
        LogisticModel().fit(np.zeros((3, 2)), np.zeros(4))
    with pytest.raises(RuntimeError):
        LogisticModel().predict_proba(np.zeros((1, 2)))


def test_metric_edge_cases():
    assert brier([], []) is None
    assert auc([0.2, 0.4], [1, 1]) is None
    assert auc([0.1, 0.9, 0.5, 0.5], [0, 1, 0, 1]) == pytest.approx(0.875)
    rows = reliability([0.05, 0.95, 1.0], [0, 1, 1], 10)
    assert [r["n"] for r in rows] == [1, 2] and rows[-1]["hi"] == 1.0
