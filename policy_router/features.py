"""Per (cycle, node) features for the router.

Context text = the INDEX REGIME label + holdings + watchlist + quarantine (one "state" chunk), the
event-calendar block when the cycle's inputs carry it, and the cycle's summaries (each headline and
each insights paragraph is one chunk). The context vector is the normalized mean of the chunk
vectors, so a long cycle never overflows the embedding model's window.

FEATURES (one row per routable node):
    cos_ctx          cosine(context vector, node vector)
    max_chunk        max cosine between the node and any headline / insights / event chunk
    route_*          the deterministic route flags of policy_graph.assembly, each computed on its own:
                     regime, ticker (holdings + watchlist), news, entities, trend, quarantine, recent
    prior_logit      logit of the node's Beta-smoothed historical needed-rate (Priors)
    kind_*           one-hot node kind (entry, ltm, lesson)
    age_months       diary entries: months since the entry date (capped at 6); 0 otherwise
    ltm_weight       memory rows: decider_memory weight - 1; 0 otherwise

Embedding roles follow nomic-embed-text v1.5: context chunks and reasons are queries
("search_query: "), guidelines are documents ("search_document: "). The prefixes are settings and
travel with the model artifact.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Callable, Optional, Sequence

import numpy as np

from policy_graph import assembly

QUERY_PREFIX = "search_query: "
DOC_PREFIX = "search_document: "
MAX_HEADLINES_PER_SUMMARY = 5
MAX_SUMMARIES = 10
MAX_INSIGHT_CHARS = 1500
AGE_CAP_MONTHS = 6.0

KINDS = ("entry", "ltm", "lesson")
ROUTE_FLAGS = ("regime", "ticker", "news", "entities", "trend", "quarantine", "recent")
FEATURES = (("cos_ctx", "max_chunk") + tuple(f"route_{r}" for r in ROUTE_FLAGS) + ("prior_logit",)
            + tuple(f"kind_{k}" for k in KINDS) + ("age_months", "ltm_weight"))

_HEADLINE_TICKER_RE = re.compile(r"\[([A-Z]{1,5})\]")
_WATCHLIST_LINE_RE = re.compile(r"Watchlist:\s*([A-Z0-9 ,;/&]+)", re.I)


# ----------------------------------------------------------------------------- cycle context
@dataclass
class CycleContext:
    """What the Decider is shown this cycle, reduced to what the router reads."""
    run_id: str = ""
    regime: str = ""
    holdings: list = dc_field(default_factory=list)
    watchlist: list = dc_field(default_factory=list)
    quarantined: list = dc_field(default_factory=list)
    news: list = dc_field(default_factory=list)
    entities: list = dc_field(default_factory=list)
    trend: list = dc_field(default_factory=list)
    summaries: list = dc_field(default_factory=list)     # [{"agent", "headlines": [...], "insights": str}]
    event_block: str = ""
    today: Optional[datetime] = None

    def assembly_context(self) -> assembly.Context:
        return assembly.Context(regime=self.regime or "", holdings=list(self.holdings), watchlist=list(self.watchlist),
                                quarantined=list(self.quarantined), news=list(self.news),
                                entities=list(self.entities), trend=list(self.trend), today=self.today)

    def state_line(self) -> str:
        def j(xs):
            xs = [str(x).upper() for x in xs if x]
            return ", ".join(xs) if xs else "none"
        return (f"INDEX REGIME: {self.regime or 'unknown'}. Holdings: {j(self.holdings)}. "
                f"Watchlist: {j(self.watchlist)}. Quarantine: {j(self.quarantined)}.")

    def chunks(self) -> list:
        """[(kind, text)] — kind in state | event | headline | insights."""
        out = [("state", self.state_line())]
        if (self.event_block or "").strip():
            out.append(("event", self.event_block.strip()))
        for s in (self.summaries or [])[:MAX_SUMMARIES]:
            if not isinstance(s, dict):
                continue
            for h in (s.get("headlines") or [])[:MAX_HEADLINES_PER_SUMMARY]:
                if str(h or "").strip():
                    out.append(("headline", str(h).strip()))
            ins = str(s.get("insights") or "").strip()
            if ins:
                out.append(("insights", ins[:MAX_INSIGHT_CHARS]))
        return out

    def text(self, limit: int = 6000) -> str:
        """The context as one text (for the LLM tier and the logs)."""
        parts = [t for _k, t in self.chunks()]
        return "\n".join(parts)[:limit]


def parse_summary_row(data) -> Optional[dict]:
    """{"agent", "headlines", "insights"} from a `summaries.data` payload (as the Decider parses it)."""
    try:
        parsed = json.loads(data) if isinstance(data, str) else (data or {})
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary", {})
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except ValueError:
            summary = {"headlines": [], "insights": summary}
    if not isinstance(summary, dict):
        return None
    heads = summary.get("headlines") or []
    return {"agent": parsed.get("agent") or "", "headlines": [str(h) for h in heads if h][:MAX_HEADLINES_PER_SUMMARY],
            "insights": str(summary.get("insights") or "")}


def tickers_in_summaries(parsed_summaries) -> list:
    """`[TICKER]` headline prefixes and the `Watchlist: …` line of each insight (the Decider's news route)."""
    out = []
    for s in parsed_summaries or []:
        if not isinstance(s, dict):
            continue
        for h in s.get("headlines") or []:
            out.extend(_HEADLINE_TICKER_RE.findall(str(h)))
        m = _WATCHLIST_LINE_RE.search(str(s.get("insights") or ""))
        if m:
            out.extend(t.strip().upper() for t in re.split(r"[,;/ ]+", m.group(1))
                       if 1 <= len(t.strip()) <= 5 and t.strip().isalpha())
    return list(dict.fromkeys(t for t in out if t))


# ----------------------------------------------------------------------------- priors
class Priors:
    """Beta-smoothed historical needed-rate per node: (needed + s * r_kind) / (n + s), where r_kind
    is the pooled rate of the node's kind (an unseen node gets its kind's rate)."""

    def __init__(self, counts: Optional[dict] = None, kind_counts: Optional[dict] = None, strength: float = 4.0):
        self.counts = {k: [int(v[0]), int(v[1])] for k, v in (counts or {}).items()}
        self.kind_counts = {k: [int(v[0]), int(v[1])] for k, v in (kind_counts or {}).items()}
        self.strength = float(strength)

    def kind_rate(self, kind: str) -> float:
        a, n = self.kind_counts.get(kind, (0, 0))
        return (a + 1.0) / (n + 2.0)                 # Laplace: 0.5 with no data

    def p(self, node_id: str, kind: str) -> float:
        a, n = self.counts.get(node_id, (0, 0))
        return (a + self.strength * self.kind_rate(kind)) / (n + self.strength)

    def update(self, node_id: str, kind: str, needed: bool) -> None:
        c = self.counts.setdefault(node_id, [0, 0])
        k = self.kind_counts.setdefault(kind, [0, 0])
        c[0] += int(bool(needed))
        c[1] += 1
        k[0] += int(bool(needed))
        k[1] += 1

    def copy(self) -> "Priors":
        return Priors(self.counts, self.kind_counts, self.strength)

    def to_dict(self) -> dict:
        return {"strength": self.strength, "counts": self.counts, "kind_counts": self.kind_counts}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Priors":
        d = d or {}
        return cls(d.get("counts"), d.get("kind_counts"), d.get("strength", 4.0))


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


# ----------------------------------------------------------------------------- texts
def node_text(node, prefix: str = DOC_PREFIX) -> str:
    return prefix + (node.text or "")


def chunk_texts(ctx: CycleContext, prefix: str = QUERY_PREFIX) -> list:
    return [(k, prefix + t) for k, t in ctx.chunks()]


def texts_for(ctx: CycleContext, nodes: Sequence, *, query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> list:
    """Every text one cycle's features need, in one list (one embedding call)."""
    return [t for _k, t in chunk_texts(ctx, query_prefix)] + [node_text(n, doc_prefix) for n in nodes]


# ----------------------------------------------------------------------------- route flags
def route_flags(node, ctx: CycleContext) -> dict:
    """Each deterministic route of policy_graph.assembly, evaluated on its own (multi-hot)."""
    body = node.text or ""
    mine = set(node.tickers)
    actx = ctx.assembly_context()
    today = ctx.today or datetime.now()
    recent = False
    if node.kind == "entry" and node.date is not None:
        recent = (today - node.date).days <= assembly.RECENT_DAYS
    words = assembly.REGIME_WORDS.get((ctx.regime or "").upper()) or ()
    low = body.lower()
    return {
        "regime": bool(words) and any(w in low for w in words),
        "ticker": bool(mine & actx.tickers),
        "news": bool(mine & actx.news_tickers),
        "entities": bool(mine & actx.entity_tickers),
        "trend": bool(mine & actx.trend_tickers),
        "quarantine": bool(ctx.quarantined) and bool(assembly.QUARANTINE_RE.search(body)),
        "recent": recent,
    }


def today_route(node, ctx: CycleContext) -> Optional[str]:
    """The route today's assembly would give this node (None = dropped); memory rows have no route."""
    if node.node is None or node.kind == "ltm":
        return None
    return assembly.route_for(node.node, ctx.assembly_context(), field=node.field or "memory")


# ----------------------------------------------------------------------------- feature rows
def feature_rows(ctx: CycleContext, nodes: Sequence, vec_of: Callable[[str], np.ndarray], priors: Priors, *,
                 query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> np.ndarray:
    """(len(nodes), len(FEATURES)) matrix. `vec_of(text)` returns the unit vector of an embedded text."""
    chunks = chunk_texts(ctx, query_prefix)
    cvecs = np.vstack([vec_of(t) for _k, t in chunks]) if chunks else np.zeros((0, 1), dtype=np.float32)
    ctx_vec = cvecs.mean(axis=0) if len(cvecs) else None
    if ctx_vec is not None:
        nrm = float(np.linalg.norm(ctx_vec))
        ctx_vec = ctx_vec / nrm if nrm > 0 else ctx_vec
    content = np.array([k != "state" for k, _t in chunks], dtype=bool)
    today = ctx.today or datetime.now()
    rows = []
    for n in nodes:
        v = vec_of(node_text(n, doc_prefix))
        cos_ctx = float(v @ ctx_vec) if ctx_vec is not None else 0.0
        max_chunk = float((cvecs[content] @ v).max()) if content.any() else 0.0
        flags = route_flags(n, ctx)
        age = 0.0
        if n.kind == "entry" and n.date is not None:
            age = min(max((today - n.date).days / 30.0, 0.0), AGE_CAP_MONTHS)
        row = [cos_ctx, max_chunk] + [1.0 if flags[r] else 0.0 for r in ROUTE_FLAGS]
        row.append(_logit(priors.p(n.node_id, n.kind)))
        row += [1.0 if n.kind == k else 0.0 for k in KINDS]
        row += [age, (float(n.weight) - 1.0) if n.kind == "ltm" else 0.0]
        rows.append(row)
    return np.asarray(rows, dtype=np.float64).reshape(len(rows), len(FEATURES))


def build_features(ctx: CycleContext, nodes: Sequence, embedder, priors: Priors, *, budget: Optional[float] = None,
                   query_prefix: str = QUERY_PREFIX, doc_prefix: str = DOC_PREFIX) -> np.ndarray:
    """Embed everything one cycle needs in ONE call (cache first, `budget` seconds), then feature rows."""
    texts = texts_for(ctx, nodes, query_prefix=query_prefix, doc_prefix=doc_prefix)
    vecs = embedder.embed(texts, budget=budget)
    lookup = {t: vecs[i] for i, t in enumerate(texts)}
    return feature_rows(ctx, nodes, lookup.__getitem__, priors, query_prefix=query_prefix, doc_prefix=doc_prefix)


__all__ = ["CycleContext", "Priors", "FEATURES", "KINDS", "ROUTE_FLAGS", "QUERY_PREFIX", "DOC_PREFIX",
           "feature_rows", "build_features", "route_flags", "today_route", "texts_for", "node_text",
           "chunk_texts", "parse_summary_row", "tickers_in_summaries"]
