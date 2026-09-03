"""Graph-driven runtime assembly for the Decider (Phase 3, step 1).

The stored prompt is the contract (same bytes as the guideline files). What the model *reads*
each cycle can be built from the graph instead of the flat text: every guideline is selected
and ordered by a deterministic query over the cycle's context, and rendered with its id and
its realized record so the model can weigh rules by evidence. No LLM routes anything.

Routes (why a guideline reached the prompt — recorded per run for route importance):

    core        locked structure and every numbered rule (the policy itself is never trimmed)
    regime      the guideline's text or tags name the current regime (RISK-ON / MIXED / RISK-OFF)
    ticker      it cites a ticker in holdings or on the watchlist (graph `cites` edges / tickers)
    quarantine  quarantine / re-entry guidance while the quarantine line is non-empty
    recent      a memory log entry dated within RECENT_DAYS
    reminder    the weekly "Latest Feedback Reminder" section
    identity    soul sections (always, verbatim)
    context     section preambles / group text kept so the structure stays readable

Older log entries (the diary) are dropped from the rendering and listed by id in a one-line
tail so the model can still cite them; rules and lessons are never trimmed.

Rendering: each guideline body is followed by ` ⟨id · cited 7d/30d/90d: a/b/c · win 58% n=12⟩`
(or ` ⟨id⟩` when it has no record). Plain strings in, plain strings out; stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from typing import Optional

from .model import COMPILED_FIELDS, Version

RECENT_DAYS = 30
REGIME_WORDS = {
    "RISK-ON": ("risk-on", "risk on"),
    "MIXED": ("mixed",),
    "RISK-OFF": ("risk-off", "risk off"),
}
QUARANTINE_RE = re.compile(r"quarantin|re-?entry|re-?enter", re.I)
TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
DATE_RE = re.compile(r"\.(\d{4})_(\d{2})_(\d{2})")


@dataclass
class Context:
    regime: str = ""                      # RISK-ON | MIXED | RISK-OFF | ""
    holdings: list = dc_field(default_factory=list)
    watchlist: list = dc_field(default_factory=list)
    quarantined: list = dc_field(default_factory=list)
    today: Optional[datetime] = None

    @property
    def tickers(self) -> set:
        return {str(t).upper() for t in list(self.holdings) + list(self.watchlist) if t}


@dataclass
class Selected:
    node_id: str
    route: str
    field: str


@dataclass
class Assembled:
    strategy_directives: str
    memory: str
    soul: str
    served: list                         # [Selected] in rendered order
    dropped: list                        # node ids left out of the rendering
    health_used: bool


# ----------------------------------------------------------------------------- selection
def _entry_date(node_id: str) -> Optional[datetime]:
    m = DATE_RE.search(node_id)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _mentions_regime(text: str, regime: str) -> bool:
    words = REGIME_WORDS.get((regime or "").upper())
    if not words:
        return False
    low = (text or "").lower()
    return any(w in low for w in words)


def _node_tickers(node) -> set:
    out = {str(t).upper() for t in (node.tickers or [])}
    out |= {str(t).upper() for t in (node.tags or []) if TICKER_RE.fullmatch(str(t).upper() or "")}
    return out


def route_for(node, ctx: Context, *, field: str) -> Optional[str]:
    """The route that keeps this guideline in the prompt, or None to drop it."""
    nt = node.node_type
    if nt in ("field",):
        return "context"
    if field == "soul":
        return "identity"
    if nt == "reminder":
        return "reminder"
    if node.locked or nt == "rule" or nt == "section":
        return "core"
    # lessons are policy and always stay; the specific route is recorded when one applies
    if ctx.regime and _mentions_regime(node.body, ctx.regime):
        return "regime"
    if _node_tickers(node) & ctx.tickers:
        return "ticker"
    if ctx.quarantined and QUARANTINE_RE.search(node.body or ""):
        return "quarantine"
    if nt == "entry":                # dated log entries are the diary: only recent ones stay
        d = _entry_date(node.id)
        today = ctx.today or datetime.now()
        if d is not None and (today - d) <= timedelta(days=RECENT_DAYS):
            return "recent"
        return None
    if nt == "lesson":
        return "core"
    return "context"


def _ordered_ids(version: Version, field: str) -> list:
    meta = (version.manifest.get("fields") or {}).get(field) or {}
    if meta.get("inherited"):
        return [n.id for n in sorted((x for x in version.nodes.values() if x.field == field and x.owner == "default-file"),
                                     key=lambda n: (n.order, n.id))]
    return list((version.manifest.get("compile_order") or {}).get(field, []))


def select(version: Version, ctx: Context) -> tuple:
    """(served [Selected], dropped [ids]) over the three evolving fields. Document order is kept,
    except that within a section the rules naming the current regime move to the front."""
    served, dropped = [], []
    for field in COMPILED_FIELDS:
        ids = _ordered_ids(version, field)
        kept = []
        for i in ids:
            n = version.nodes.get(i)
            if n is None:
                continue
            r = route_for(n, ctx, field=field)
            if r is None:
                dropped.append(i)
            else:
                kept.append((i, r))
        if ctx.regime:
            by_parent: dict = {}
            for i, r in kept:
                if version.nodes[i].node_type == "rule":
                    by_parent.setdefault(version.nodes[i].parent, []).append((i, r))
            reordered = {}
            for parent, rules in by_parent.items():
                hot = [x for x in rules if _mentions_regime(version.nodes[x[0]].body, ctx.regime)]
                cold = [x for x in rules if x not in hot]
                reordered[parent] = hot + cold
            used = {p: 0 for p in reordered}
            out = []
            for i, r in kept:            # rule children are contiguous within their parent: slot-replace
                n = version.nodes[i]
                if n.node_type == "rule" and n.parent in reordered:
                    out.append(reordered[n.parent][used[n.parent]])
                    used[n.parent] += 1
                else:
                    out.append((i, r))
            kept = out
        served.extend(Selected(node_id=i, route=r, field=field) for i, r in kept)
    return served, dropped


# ----------------------------------------------------------------------------- rendering
def health_tag(node_id: str, health: Optional[dict]) -> str:
    """` ⟨id · cited 7d/30d/90d: 3/12/20 · win 58% n=12⟩` (or ` ⟨id⟩`)."""
    h = (health or {}).get(node_id) if health else None
    if not h:
        return f" ⟨{node_id}⟩"
    c7, c30, c90 = (int((h.get(w) or {}).get("cited", 0)) for w in ("7d", "30d", "90d"))
    parts = [node_id]
    if c90:
        parts.append(f"cited 7d/30d/90d: {c7}/{c30}/{c90}")
    o = h.get("90d") or {}
    if o.get("closed"):
        wr = o.get("win_rate")
        parts.append(f"win {round(float(wr) * 100)}% n={o['closed']}" if wr is not None else f"n={o['closed']}")
    return " ⟨" + " · ".join(parts) + "⟩"


def render_field(version: Version, served: list, field: str, health: Optional[dict]) -> str:
    parts = []
    for s in served:
        if s.field != field:
            continue
        n = version.nodes[s.node_id]
        body = n.body
        if n.node_type in ("rule", "lesson", "entry", "section", "note", "identity", "reminder") and (body or "").strip():
            body = body.rstrip() + health_tag(s.node_id, health)
            tail = n.sep_after if n.sep_after else "\n"
        else:
            tail = n.sep_after
        parts.append(n.sep_before + body + tail)
    return "".join(parts).strip("\n")


def assemble(version: Version, ctx: Context, *, health: Optional[dict] = None) -> Assembled:
    served, dropped = select(version, ctx)
    sd = render_field(version, served, "strategy_directives", health)
    mem = render_field(version, served, "memory", health)
    soul = render_field(version, served, "soul", health)
    if dropped:
        listed = ", ".join(dropped[:40]) + (" …" if len(dropped) > 40 else "")
        mem = (mem + f"\n\nNot shown this cycle (not relevant to today's regime, holdings or watchlist; still citable by id): {listed}").strip()
    return Assembled(strategy_directives=sd, memory=mem, soul=soul, served=served, dropped=dropped,
                     health_used=bool(health))


__all__ = ["Context", "Selected", "Assembled", "route_for", "select", "assemble", "health_tag", "render_field",
           "RECENT_DAYS"]
