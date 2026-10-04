"""Shared fakes for the policy router tests: a bag-of-words embeddings transport (OpenAI response shape) and
small node / context builders. Not a test module (no test_ prefix)."""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime

import numpy as np

from policy_router.features import CycleContext
from policy_router.nodes import RouterNode

DIM = 96
_PREFIX_WORDS = {"search", "query", "document"}


def bow_vector(text: str, dim: int = DIM) -> list:
    v = np.zeros(dim)
    for w in re.findall(r"[a-z0-9]+", str(text).lower()):
        if w in _PREFIX_WORDS:
            continue
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    if not v.any():
        v[0] = 1.0
    return list(v)


class FakeEmbeddingsTransport:
    """transport(url, payload, timeout) answering like LM Studio's /v1/embeddings; counts calls and inputs."""

    def __init__(self, delay: float = 0.0, fail: Exception = None):
        self.calls = 0
        self.inputs = []
        self.delay = delay
        self.fail = fail

    def __call__(self, url, payload, timeout):
        assert url.endswith("/embeddings")
        self.calls += 1
        self.inputs.extend(payload["input"])
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return {"object": "list", "model": payload["model"],
                "data": [{"object": "embedding", "index": i, "embedding": bow_vector(t)}
                         for i, t in reversed(list(enumerate(payload["input"])))]}   # out of order on purpose


def node(node_id: str, kind: str, text: str, *, tickers=(), tags=(), weight: float = 1.0, date=None, chars=None):
    return RouterNode(node_id=node_id, kind=kind, text=text, chars=len(text) if chars is None else chars,
                      tickers=frozenset(tickers), tags=frozenset(tags), weight=weight, date=date)


def context(**kw) -> CycleContext:
    base = dict(run_id="20261002T123048", regime="RISK-ON", holdings=["QCOM", "TMO"], watchlist=["ISRG", "NET"],
                quarantined=["IRDM"], news=["MU", "NKE"], entities=["NVDA"], trend=["MRVL"],
                summaries=[{"agent": "a", "headlines": ["[MU] Micron beats but shares fall on priced kill worries"],
                            "insights": "Semis weak; Watchlist: MU, NKE"}],
                event_block="# EVENT CALENDAR FOMC in 18 sessions", today=datetime(2026, 10, 2, 12, 0))
    base.update(kw)
    return CycleContext(**base)
