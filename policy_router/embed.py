"""OpenAI-compatible embeddings client (LM Studio's `POST /v1/embeddings`) with a cache and a hard budget.

    client = EmbeddingClient("http://127.0.0.1:1234/v1", "text-embedding-nomic-embed-text-v1.5",
                             cache=EmbedCache(path))
    vecs = client.embed(["search_query: …", "search_document: …"], budget=5.0)   # (n, d), unit rows

* Cache: one sqlite file keyed by sha256(model + "\\n" + text) → float32 vector, so a node text is
  embedded once per model, ever. `EmbedCache(None)` keeps the cache in memory (tests).
* Budget: `budget` seconds of wall clock for ALL uncached batches of the call. Each HTTP request runs
  in a worker thread and is abandoned when the budget is spent (`EmbedTimeout`); the decision cycle
  never waits longer than that. `budget=None` (training) only applies the per-request timeout.
* Transport: `transport(url, payload, timeout) -> dict` (default: urllib, stdlib). Tests pass a fake.

stdlib + numpy; never imports config, never reads the environment.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
MAX_TEXT_CHARS = 3000          # ~750 tokens: inside the 2048-token window LM Studio gives embedding models
BATCH_SIZE = 48

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="policy-router-http")


class EmbedError(RuntimeError):
    """The embeddings endpoint failed or answered something unusable."""


class EmbedTimeout(EmbedError):
    """The wall-clock budget ran out before every text was embedded."""


# ----------------------------------------------------------------------------- transport (stdlib)
def http_post_json(url: str, payload: dict, timeout: float) -> dict:
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=max(0.1, float(timeout))) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(url: str, timeout: float) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=max(0.1, float(timeout))) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_with_deadline(fn: Callable, timeout: float):
    """Run `fn()` in a worker thread and wait at most `timeout` seconds (TimeoutError otherwise)."""
    fut = _POOL.submit(fn)
    try:
        return fut.result(timeout=max(0.0, float(timeout)))
    except _FutureTimeout as exc:
        fut.cancel()
        raise TimeoutError(f"no answer within {timeout:.1f}s") from exc


# ----------------------------------------------------------------------------- cache
def cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


class EmbedCache:
    """sha256 → float32 vector. On disk (sqlite) when `path` is given, in memory otherwise."""

    DDL = "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, model TEXT, dim INTEGER, vec BLOB, created_at REAL)"

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self._mem: dict = {}
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self._connect() as conn:
                    conn.execute(self.DDL)
            except Exception:       # noqa: BLE001 — an unwritable cache degrades to memory only
                self.path = None

    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=2.0)

    def get_many(self, keys: Sequence[str]) -> dict:
        out = {k: self._mem[k] for k in keys if k in self._mem}
        missing = [k for k in keys if k not in out]
        if missing and self.path is not None:
            try:
                with self._connect() as conn:
                    for i in range(0, len(missing), 500):
                        chunk = missing[i:i + 500]
                        q = "SELECT key, vec FROM embeddings WHERE key IN (%s)" % ",".join("?" * len(chunk))
                        for k, blob in conn.execute(q, chunk):
                            v = np.frombuffer(blob, dtype=np.float32).copy()
                            self._mem[k] = v
                            out[k] = v
            except Exception:       # noqa: BLE001 — a cache read failure is a cache miss
                pass
        return out

    def put_many(self, items: dict, model: str = "") -> None:
        for k, v in items.items():
            self._mem[k] = np.asarray(v, dtype=np.float32)
        if self.path is None or not items:
            return
        try:
            now = time.time()
            with self._connect() as conn:
                conn.executemany("INSERT OR REPLACE INTO embeddings (key, model, dim, vec, created_at) VALUES (?, ?, ?, ?, ?)",
                                 [(k, model, int(len(v)), np.asarray(v, dtype=np.float32).tobytes(), now)
                                  for k, v in items.items()])
        except Exception:           # noqa: BLE001 — never fail a cycle on a cache write
            pass

    def __len__(self) -> int:
        return len(self._mem)


# ----------------------------------------------------------------------------- client
def _unit(rows: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    if rows.ndim == 1:
        rows = rows[None, :]
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return rows / norms


class EmbeddingClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_EMBED_MODEL, *,
                 cache: Optional[EmbedCache] = None, timeout: float = 30.0, batch_size: int = BATCH_SIZE,
                 transport: Optional[Callable] = None, max_chars: int = MAX_TEXT_CHARS):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_EMBED_MODEL
        self.cache = cache if cache is not None else EmbedCache(None)
        self.timeout = float(timeout)
        self.batch_size = max(1, int(batch_size))
        self.transport = transport or http_post_json
        self.max_chars = int(max_chars)
        self.calls = 0              # HTTP requests made (tests and logs)

    def _clip(self, text: str) -> str:
        t = str(text or "").strip() or "(empty)"
        return t[: self.max_chars]

    def _request(self, batch: list, timeout: float) -> list:
        payload = {"model": self.model, "input": batch}
        resp = self.transport(f"{self.base_url}/embeddings", payload, timeout)
        data = (resp or {}).get("data") if isinstance(resp, dict) else None
        if not isinstance(data, list) or len(data) != len(batch):
            raise EmbedError(f"embeddings answer has {len(data) if isinstance(data, list) else 'no'} rows for {len(batch)} inputs")
        rows = sorted(data, key=lambda d: int(d.get("index", 0)) if isinstance(d, dict) else 0)
        out = []
        for d in rows:
            vec = d.get("embedding") if isinstance(d, dict) else None
            if not isinstance(vec, list) or not vec:
                raise EmbedError("embeddings answer row without a vector")
            out.append(np.asarray(vec, dtype=np.float32))
        return out

    def embed(self, texts: Sequence[str], *, budget: Optional[float] = None) -> np.ndarray:
        """Unit-normalized vectors (n, d) for `texts`, in order. Raises EmbedTimeout / EmbedError."""
        texts = [self._clip(t) for t in texts]
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        keys = [cache_key(self.model, t) for t in texts]
        have = self.cache.get_many(list(dict.fromkeys(keys)))
        todo, seen = [], set()
        for k, t in zip(keys, texts):
            if k not in have and k not in seen:
                seen.add(k)
                todo.append((k, t))
        deadline = (time.monotonic() + float(budget)) if budget is not None else None
        for i in range(0, len(todo), self.batch_size):
            batch = todo[i:i + self.batch_size]
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EmbedTimeout(f"embedding budget of {budget:.1f}s spent with {len(todo) - i} texts left")
                per_call = min(self.timeout, remaining)
                try:
                    vecs = call_with_deadline(lambda b=batch, t=per_call: self._request([x[1] for x in b], t), per_call)
                except TimeoutError as exc:
                    raise EmbedTimeout(f"embedding budget of {budget:.1f}s spent ({exc})") from exc
                except EmbedError:
                    raise
                except Exception as exc:     # noqa: BLE001 — connection refused, HTTP error, bad JSON
                    raise EmbedError(f"{type(exc).__name__}: {exc}") from exc
            else:
                try:
                    vecs = self._request([x[1] for x in batch], self.timeout)
                except EmbedError:
                    raise
                except Exception as exc:     # noqa: BLE001
                    raise EmbedError(f"{type(exc).__name__}: {exc}") from exc
            self.calls += 1
            fresh = {k: v for (k, _t), v in zip(batch, vecs)}
            self.cache.put_many(fresh, self.model)
            have.update(fresh)
        dims = {len(have[k]) for k in keys}
        if len(dims) != 1:
            raise EmbedError(f"mixed embedding sizes {sorted(dims)} (model changed under the cache?)")
        return _unit(np.vstack([have[k] for k in keys]))


__all__ = ["EmbeddingClient", "EmbedCache", "EmbedError", "EmbedTimeout", "cache_key", "http_post_json",
           "http_get_json", "call_with_deadline", "DEFAULT_BASE_URL", "DEFAULT_EMBED_MODEL"]
