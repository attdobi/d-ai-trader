"""policy_router.embed + features with a fake OpenAI-compatible embeddings endpoint: batching, the sha256
cache (memory and sqlite), the hard budget, and every feature column."""
from __future__ import annotations

import importlib.util
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from policy_router import features as F
from policy_router.embed import EmbedCache, EmbedError, EmbeddingClient, EmbedTimeout, cache_key

_spec = importlib.util.spec_from_file_location("policy_router_fakes", Path(__file__).resolve().parent / "policy_router_fakes.py")
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)


def test_client_batches_orders_normalizes_and_caches(tmp_path):
    t = fakes.FakeEmbeddingsTransport()
    cache = EmbedCache(tmp_path / "cache.sqlite3")
    c = EmbeddingClient("http://fake/v1/", "m1", cache=cache, transport=t, batch_size=2)
    texts = ["alpha beta", "gamma", "alpha beta", "delta epsilon"]
    v = c.embed(texts)
    assert v.shape == (4, fakes.DIM) and t.calls == 2                  # 3 unique texts, batches of 2
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, rtol=1e-6)
    np.testing.assert_allclose(v[0], v[2])
    expected = np.asarray(fakes.bow_vector("gamma"))
    np.testing.assert_allclose(v[1], expected / np.linalg.norm(expected), rtol=1e-6)   # index order restored
    v2 = c.embed(texts)                                                  # memory cache: no new request
    assert t.calls == 2
    np.testing.assert_allclose(v, v2)
    fresh = EmbeddingClient("http://fake/v1", "m1", cache=EmbedCache(tmp_path / "cache.sqlite3"), transport=t)
    fresh.embed(["gamma", "delta epsilon"])                              # sqlite cache survives a new client
    assert t.calls == 2
    other_model = EmbeddingClient("http://fake/v1", "m2", cache=EmbedCache(tmp_path / "cache.sqlite3"), transport=t)
    other_model.embed(["gamma"])                                         # the key includes the model
    assert t.calls == 3
    assert cache_key("m1", "x") != cache_key("m2", "x")


def test_client_budget_timeout_and_errors():
    slow = fakes.FakeEmbeddingsTransport(delay=0.5)
    c = EmbeddingClient("http://fake/v1", "m", transport=slow)
    with pytest.raises(EmbedTimeout):
        c.embed(["one", "two"], budget=0.1)
    down = fakes.FakeEmbeddingsTransport(fail=ConnectionRefusedError("refused"))
    with pytest.raises(EmbedError):
        EmbeddingClient("http://fake/v1", "m", transport=down).embed(["x"], budget=1.0)
    bad = lambda url, payload, timeout: {"data": []}                      # noqa: E731
    with pytest.raises(EmbedError):
        EmbeddingClient("http://fake/v1", "m", transport=bad).embed(["x"])


def test_context_chunks_state_line_and_news_tickers():
    ctx = fakes.context()
    kinds = [k for k, _t in ctx.chunks()]
    assert kinds == ["state", "event", "headline", "insights"]
    assert "RISK-ON" in ctx.state_line() and "QCOM, TMO" in ctx.state_line() and "IRDM" in ctx.state_line()
    assert F.tickers_in_summaries(ctx.summaries) == ["MU", "NKE"]
    row = F.parse_summary_row('{"agent": "X", "summary": {"headlines": ["h1", "h2"], "insights": "ins"}}')
    assert row == {"agent": "X", "headlines": ["h1", "h2"], "insights": "ins"}
    assert F.parse_summary_row("not json") is None


def test_feature_rows_cover_every_column():
    ctx = fakes.context()
    nodes = [
        fakes.node("DA.memory.log.2026_09_24", "entry", "PRICED KILL in RISK-ON: MU priced kill worries",
                   tickers=["MU"], date=datetime(2026, 9, 24)),
        fakes.node("DA.memory.log.2026_06_29_irdm", "entry", "IRDM gap chase; re-entry quarantine applies",
                   tickers=["IRDM"], date=datetime(2026, 6, 29)),
        fakes.node("DA.ltm.7", "ltm", "- [mistake] (QCOM) bought QCOM extended", tickers=["QCOM"], weight=1.5),
        fakes.node("DA.memory.lessons.regime", "lesson", "Unrelated words entirely", tickers=["NVDA", "MRVL"]),
    ]
    t = fakes.FakeEmbeddingsTransport()
    emb = EmbeddingClient("http://fake/v1", "m", transport=t)
    priors = F.Priors({"DA.ltm.7": [9, 10]}, {"ltm": [1, 10]}, strength=4.0)
    X = F.build_features(ctx, nodes, emb, priors, budget=2.0)
    assert t.calls == 1                                                  # one embedding call per cycle
    assert X.shape == (4, len(F.FEATURES))
    col = {name: X[:, i] for i, name in enumerate(F.FEATURES)}
    assert col["cos_ctx"][0] > col["cos_ctx"][3]                         # shares words with the headline
    assert col["max_chunk"][0] > 0.4
    assert list(col["route_regime"]) == [1, 0, 0, 0]
    assert list(col["route_news"]) == [1, 0, 0, 0]
    assert list(col["route_ticker"]) == [0, 0, 1, 0]                     # QCOM is held
    assert list(col["route_entities"]) == [0, 0, 0, 1] and list(col["route_trend"]) == [0, 0, 0, 1]
    assert list(col["route_quarantine"]) == [0, 1, 0, 0]                 # quarantine line is non-empty
    assert list(col["route_recent"]) == [1, 0, 0, 0]                     # 8 days old vs 95 days old
    assert col["age_months"][0] == pytest.approx(8 / 30) and col["age_months"][1] == pytest.approx(3.1666, rel=1e-3)
    assert list(col["ltm_weight"]) == [0, 0, 0.5, 0]
    assert list(col["kind_entry"]) == [1, 1, 0, 0] and list(col["kind_ltm"]) == [0, 0, 1, 0] and col["kind_lesson"][3] == 1
    # prior: (9 + 4 * kind_rate) / (10 + 4) for the seen row; unseen nodes get their kind's Laplace rate
    kr = (1 + 1) / (10 + 2)
    assert col["prior_logit"][2] == pytest.approx(math.log(((9 + 4 * kr) / 14) / (1 - (9 + 4 * kr) / 14)))
    assert col["prior_logit"][0] == pytest.approx(0.0)                   # entry kind unseen: 0.5


def test_priors_update_round_trip_and_today_route():
    p = F.Priors(strength=2.0)
    assert p.p("x", "entry") == pytest.approx(0.5)
    for needed in (True, True, False):
        p.update("x", "entry", needed)
    assert p.counts["x"] == [2, 3] and p.kind_counts["entry"] == [2, 3]
    q = F.Priors.from_dict(p.to_dict())
    assert q.p("x", "entry") == pytest.approx(p.p("x", "entry"))
    ctx = fakes.context()
    assert F.today_route(fakes.node("DA.ltm.1", "ltm", "x"), ctx) is None
