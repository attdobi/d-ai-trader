"""One routing decision at decision time — off | shadow | active, and every failure means today's prompt.

    settings = RouterSettings.from_mapping(env, repo_root=root, config_hash=cfg)   # the CALLER passes its environment
    result = route_cycle(settings, ctx, nodes, today_ids=ids)                             # never raises
    result.effective_mode  → "shadow" | "active" | "fallback"

shadow    the routing decision is computed and logged every cycle; the Decider reads exactly today's prompt.
active    only with a CERTIFIED artifact whose certification covers the configured criterion
          (DAI_ROUTER_CERTIFY: target | beats_today | either), recall target, routable kinds, memory cap and
          LLM tier: pinned nodes + the routable nodes the router keeps are served; excluded ids are listed in
          a tail line so they stay citable. Anything short of that runs as shadow, with the reason in `note`.
fallback  no artifact, an embedding timeout (hard budget, default 5 s), the endpoint down, a malformed
          artifact, any exception: nothing is routed and `note` says why (the caller logs one line).

Certification criteria (recorded by the trainer in certification.criteria / certification.criterion):
    target       held-out recall >= the recall target
    beats_today  held-out recall >= today's assembly's held-out recall AND the router's served routable
                 chars <= today's, on the same held-out cycles
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from . import AGENT_DIR, DEFAULT_ROUTABLE, ROUTABLE_KINDS
from .embed import DEFAULT_BASE_URL, DEFAULT_EMBED_MODEL, EmbedCache, EmbeddingClient, EmbedTimeout
from .features import DOC_PREFIX, QUERY_PREFIX, CycleContext, Priors, build_features
from .model import LogisticModel
from .select import Selection, select_subgraph

MODES = ("off", "shadow", "active")
CERTIFY_MODES = ("target", "beats_today", "either")
ARTIFACT_NAME = "model.json"
CACHE_NAME = "embed-cache.sqlite3"
TAIL_PREFIX = "Memory rows not shown this cycle (routed out for this cycle's context; still citable by id): "


def router_root(repo_root, agent_dir: str = AGENT_DIR) -> Path:
    return Path(repo_root) / "agents" / agent_dir / "policy-router"


def artifact_path(repo_root, config_hash: str, agent_dir: str = AGENT_DIR) -> Path:
    return router_root(repo_root, agent_dir) / config_hash / ARTIFACT_NAME


def _mode(raw) -> str:
    s = str(raw if raw is not None else "shadow").strip().lower()
    if s in ("0", "false", "no", "off", "disabled", "none"):
        return "off"
    if s in ("active", "on-active", "enforce", "live"):
        return "active"
    return "shadow"


def _certify(raw) -> str:
    """DAI_ROUTER_CERTIFY: target | beats_today | either (default). An unrecognized value fails closed to
    "target", the original rule."""
    s = str(raw if raw is not None else "either").strip().lower().replace("-", "_").replace(" ", "_")
    if not s or s in ("either", "any"):
        return "either"
    if s in ("beats_today", "beats", "today"):
        return "beats_today"
    return "target"


def _float(raw, default: float, lo: float, hi: float) -> float:
    try:
        return min(max(float(raw), lo), hi)
    except (TypeError, ValueError):
        return default


def _int(raw, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class RouterSettings:
    mode: str = "shadow"
    base_url: str = DEFAULT_BASE_URL
    embed_model: str = DEFAULT_EMBED_MODEL
    llm_model: str = ""
    recall_target: float = 0.98
    certify: str = "either"                          # which certification criterion lets active run
    routable: tuple = DEFAULT_ROUTABLE
    ltm_limit: int = 14
    embed_budget_s: float = 5.0
    llm_budget_s: float = 15.0
    artifact_path: Optional[Path] = None
    cache_path: Optional[Path] = None

    @classmethod
    def from_mapping(cls, env: Mapping, *, repo_root, config_hash: str, agent_dir: str = AGENT_DIR) -> "RouterSettings":
        """Settings from a mapping of DAI_* keys (the caller passes the process environment; this package never reads it)."""
        env = env or {}
        routable = tuple(k.strip().lower() for k in str(env.get("DAI_ROUTER_ROUTABLE") or ",".join(DEFAULT_ROUTABLE)).split(",")
                         if k.strip().lower() in ROUTABLE_KINDS) or DEFAULT_ROUTABLE
        return cls(
            mode=_mode(env.get("DAI_POLICY_ROUTER", "shadow")),
            base_url=str(env.get("DAI_ROUTER_BASE_URL") or DEFAULT_BASE_URL).strip(),
            embed_model=str(env.get("DAI_ROUTER_EMBED_MODEL") or DEFAULT_EMBED_MODEL).strip(),
            llm_model=str(env.get("DAI_ROUTER_LLM_MODEL") or "").strip(),
            recall_target=_float(env.get("DAI_ROUTER_RECALL_TARGET", 0.98), 0.98, 0.5, 1.0),
            certify=_certify(env.get("DAI_ROUTER_CERTIFY", "either")),
            routable=tuple(dict.fromkeys(routable)),
            ltm_limit=max(0, _int(env.get("DAI_MEMORY_LT_LIMIT", 14), 14)),
            artifact_path=artifact_path(repo_root, config_hash, agent_dir),
            cache_path=router_root(repo_root, agent_dir) / CACHE_NAME,
        )


@dataclass
class RoutingResult:
    requested_mode: str
    effective_mode: str = "fallback"                 # shadow | active | fallback
    backend: str = "fallback"                        # embed | embed+llm | fallback
    model_version: str = ""
    certified: bool = False
    criterion: str = ""                              # the artifact's certification criterion: target | beats_today
    note: str = ""
    selection: Optional[Selection] = None
    latency_ms: int = 0
    nodes: dict = dc_field(default_factory=dict)     # node_id -> RouterNode (routable)
    chars_today: Optional[int] = None                # routable chars today's selection serves
    llm: dict = dc_field(default_factory=dict)
    extras: dict = dc_field(default_factory=dict)    # caller-owned (e.g. the memory rows behind DA.ltm ids)

    @property
    def active(self) -> bool:
        return self.effective_mode == "active" and self.selection is not None

    def _routable(self) -> list:
        return [d for d in (self.selection.decisions if self.selection else []) if not d.pinned]

    def choice(self, node_id: str) -> Optional[bool]:
        for d in self._routable():
            if d.node_id == node_id:
                return d.choice == "include"
        return None

    def assembly_override(self) -> dict:
        """{node_id: include?} for the routable policy-graph nodes (diary entries, lessons) — memory rows excluded."""
        return {d.node_id: d.choice == "include" for d in self._routable() if d.kind != "ltm"}

    def ltm_selected_ids(self) -> list:
        return [d.node_id for d in self._routable() if d.kind == "ltm" and d.choice == "include"]

    def ltm_excluded_ids(self) -> list:
        return [d.node_id for d in self._routable() if d.kind == "ltm" and d.choice == "exclude"]

    def routable_ids(self) -> list:
        return [d.node_id for d in self._routable()]

    def ltm_tail_line(self, limit: int = 40) -> str:
        ids = self.ltm_excluded_ids()
        if not ids:
            return ""
        return TAIL_PREFIX + ", ".join(ids[:limit]) + (" …" if len(ids) > limit else "")

    def summary_line(self) -> str:
        if self.selection is None or self.effective_mode == "fallback":
            return f"🧭 Policy router fallback (today's prompt served): {self.note or 'no decision'}"
        sel = self.selection
        kept = sum(1 for d in self._routable() if d.choice == "include")
        today = f"; today {self.chars_today:,}" if self.chars_today is not None else ""
        cert = (f", certified ({self.criterion})" if self.criterion else ", certified") if self.certified else ", not certified"
        return (f"🧭 Policy router {self.effective_mode} ({self.backend}, model {self.model_version or '?'}"
                f"{cert}): keeps {kept} of {len(self._routable())} routable "
                f"({sel.chars_selected:,} of {sel.chars_routable:,} chars{today}), expected recall {sel.expected_recall:.3f}, "
                f"{self.latency_ms} ms" + (f" · {self.note}" if self.note else ""))


# ----------------------------------------------------------------------------- artifact
_ARTIFACT_CACHE: dict = {}


def load_artifact(path) -> Optional[dict]:
    """The model artifact JSON (cached by mtime), None when the file does not exist."""
    if path is None:
        return None
    path = Path(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    key = str(path)
    hit = _ARTIFACT_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns:
        return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "policy_router" or "model" not in data:
        raise ValueError(f"{path} is not a policy router artifact")
    _ARTIFACT_CACHE[key] = (st.st_mtime_ns, data)
    return data


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def certification_criteria(artifact: dict) -> dict:
    """{"target": bool, "beats_today": bool}: the criteria the artifact's held-out evaluation passed. An
    artifact written before the beats_today criterion only knew "held-out recall >= target"."""
    crit = (artifact.get("certification") or {}).get("criteria")
    if isinstance(crit, dict):
        return {"target": bool(crit.get("target")), "beats_today": bool(crit.get("beats_today"))}
    return {"target": bool(artifact.get("certified")), "beats_today": False}


def accepted_criterion(artifact: dict, settings: RouterSettings) -> Optional[str]:
    """The criterion that certifies this artifact under DAI_ROUTER_CERTIFY, or None. "target" also needs the
    certified target to cover DAI_ROUTER_RECALL_TARGET; "beats_today" is accepted whatever that target is."""
    if not artifact.get("certified"):
        return None
    passed = certification_criteria(artifact)
    target = (artifact.get("certification") or {}).get("target")
    covers = not (_num(target) and settings.recall_target > float(target) + 1e-9)
    if settings.certify in ("target", "either") and passed["target"] and covers:
        return "target"
    if settings.certify in ("beats_today", "either") and passed["beats_today"]:
        return "beats_today"
    return None


def _criterion_gap(artifact: dict, settings: RouterSettings) -> str:
    cert = artifact.get("certification") or {}
    passed = certification_criteria(artifact)
    hr, target = cert.get("heldout_recall"), cert.get("target")
    why = []
    if settings.certify != "beats_today":
        if passed["target"] and artifact.get("certified"):
            why.append(f"certified for recall {target}, DAI_ROUTER_RECALL_TARGET asks {settings.recall_target}")
        else:
            why.append(f"held-out recall {hr:.3f} < target {target}" if _num(hr) else "recall target not met")
    if settings.certify != "target" and not passed["beats_today"]:
        tr, cs, ct = cert.get("today_recall"), cert.get("chars_selected"), cert.get("chars_today")
        why.append(f"does not beat today's assembly: recall {hr:.3f} vs today {tr:.3f}, chars {cs:,.0f} vs {ct:,.0f}"
                   if all(_num(x) for x in (hr, tr, cs, ct)) else "not shown to beat today's assembly")
    if settings.certify == "target" and passed["beats_today"]:
        why.append("it beats today's assembly, which DAI_ROUTER_CERTIFY=target does not accept")
    head = "model not certified" if not artifact.get("certified") else f"not certified under DAI_ROUTER_CERTIFY={settings.certify}"
    return f"{head} ({'; '.join(why)})"


def certification_gaps(artifact: dict, settings: RouterSettings, *, llm_refined: bool = False) -> list:
    """Why this artifact may NOT run active under these settings (empty = it may). `llm_refined` = the LLM
    tier changed p this cycle (the certification must cover that chat model)."""
    gaps = []
    cert = artifact.get("certification") or {}
    criterion = accepted_criterion(artifact, settings)
    if criterion is None:
        gaps.append(_criterion_gap(artifact, settings))
    cert_routable = set(cert.get("routable") or artifact.get("routable") or ())
    if cert_routable and set(settings.routable) != cert_routable:
        gaps.append(f"certified for routable {','.join(sorted(cert_routable))}, configured {','.join(settings.routable)}")
    cap = cert.get("ltm_cap")
    cert_cap = cap if _num(cap) and int(cap) > 0 else None        # missing / None / 0 = certified WITHOUT a memory cap
    if "ltm" in settings.routable and settings.ltm_limit:          # 0 = route_cycle serves the artifact's own cap
        if cert_cap is None or settings.ltm_limit < cert_cap:
            gaps.append(f"certified {f'with a {int(cert_cap)}-row memory cap' if cert_cap else 'without a memory-row cap'}, "
                        f"DAI_MEMORY_LT_LIMIT is {settings.ltm_limit}")
        elif criterion == "beats_today" and settings.ltm_limit != cert_cap:
            gaps.append(f"certified as beating today's assembly at a {int(cert_cap)}-row memory cap, "
                        f"DAI_MEMORY_LT_LIMIT is {settings.ltm_limit}")
    if llm_refined:
        cert_llm = cert.get("llm_model")
        if not cert_llm or cert_llm != settings.llm_model:
            gaps.append(f"the LLM tier ({settings.llm_model}) refined p, but the certification covers "
                        f"{cert_llm or 'only the base model'}")
    return gaps


# ----------------------------------------------------------------------------- one cycle
def route_cycle(settings: RouterSettings, ctx: CycleContext, nodes: Iterable, *, today_ids: Iterable = (),
                embedder=None, llm=None, artifact: Optional[dict] = None, log: Callable = print) -> Optional[RoutingResult]:
    """The cycle's routing decision. None when the router is off; otherwise a RoutingResult (never raises)."""
    if settings.mode == "off":
        return None
    t0 = time.monotonic()
    res = RoutingResult(requested_mode=settings.mode)
    try:
        art = artifact if artifact is not None else load_artifact(settings.artifact_path)
        if art is None:
            res.note = (f"no router model at {settings.artifact_path} — train one with "
                        f"`python -m policy_router.train --config-hash <hash>`")
            return res
        res.model_version = str(art.get("model_version") or "")
        res.certified = bool(art.get("certified"))
        res.criterion = str((art.get("certification") or {}).get("criterion") or ("target" if res.certified else ""))
        emb_meta = art.get("embed") or {}
        if emb_meta.get("model") and emb_meta["model"] != settings.embed_model:
            res.note = f"artifact was trained on {emb_meta['model']}, DAI_ROUTER_EMBED_MODEL is {settings.embed_model}"
            return res
        model = LogisticModel.from_dict(art["model"])
        priors = Priors.from_dict(art.get("priors"))
        routable = [n for n in nodes if n.kind in settings.routable]
        res.nodes = {n.node_id: n for n in routable}
        today = set(today_ids or ())
        res.chars_today = int(sum(n.chars for n in routable if n.node_id in today))
        sel_cfg = art.get("selection") or {}
        if not routable:
            res.selection = select_subgraph([], tau_min=float(sel_cfg.get("tau_min", 0.5)),
                                            recall_target=float(sel_cfg.get("recall_target", 0.98)))
            res.backend = "embed"
            res.effective_mode = "shadow"
            res.note = "no routable nodes this cycle"
            return res
        if embedder is None:
            embedder = EmbeddingClient(settings.base_url, settings.embed_model, cache=EmbedCache(settings.cache_path),
                                       timeout=settings.embed_budget_s)
        X = build_features(ctx, routable, embedder, priors, budget=settings.embed_budget_s,
                           query_prefix=emb_meta.get("query_prefix", QUERY_PREFIX),
                           doc_prefix=emb_meta.get("doc_prefix", DOC_PREFIX))
        p = [float(x) for x in model.predict_proba(X)]
        p_base = list(p)
        backend = "embed"
        if settings.llm_model:
            if llm is None:
                from .llm_tier import LLMTier
                llm = LLMTier(settings.base_url, settings.llm_model, budget_s=settings.llm_budget_s, log=log)
            refined, info = llm.refine(ctx.text(), [(n.node_id, n.text, p[i]) for i, n in enumerate(routable)])
            res.llm = info
            if refined:
                backend = "embed+llm"
                p = [refined.get(n.node_id, p[i]) for i, n in enumerate(routable)]
        items = [(n.node_id, n.kind, p[i], n.chars) for i, n in enumerate(routable)]
        max_kind = dict(sel_cfg.get("max_per_kind") or {})
        if "ltm" in settings.routable:
            max_kind["ltm"] = settings.ltm_limit if settings.ltm_limit else max_kind.get("ltm")
        sel = select_subgraph(items, tau_min=float(sel_cfg.get("tau_min", 0.5)),
                              recall_target=float(sel_cfg.get("recall_target", settings.recall_target)),
                              min_per_kind=sel_cfg.get("min_per_kind") or None,
                              max_per_kind={k: v for k, v in max_kind.items() if v} or None)
        base_by = {n.node_id: p_base[i] for i, n in enumerate(routable)}
        for d in sel.decisions:
            if backend == "embed+llm" and abs(base_by.get(d.node_id, d.p) - d.p) > 1e-12:
                d.p_base = base_by.get(d.node_id)
        res.selection = sel
        res.backend = backend
        if settings.mode == "active":
            # the trainer certifies the embed-only model: an LLM-refined p is not covered unless the
            # certification names that chat model, so such a cycle runs as shadow (an offline tier changes nothing)
            gaps = certification_gaps(art, settings, llm_refined=(backend == "embed+llm"))
            if gaps:
                res.effective_mode = "shadow"
                res.note = "active requested but running as shadow: " + "; ".join(gaps)
            else:
                res.effective_mode = "active"
        else:
            res.effective_mode = "shadow"
        return res
    except EmbedTimeout as exc:
        res.selection, res.effective_mode, res.backend = None, "fallback", "fallback"
        res.note = f"embedding timeout: {exc}"
        return res
    except Exception as exc:     # noqa: BLE001 — the router never breaks a decision cycle
        res.selection, res.effective_mode, res.backend = None, "fallback", "fallback"
        res.note = f"{type(exc).__name__}: {exc}"
        return res
    finally:
        res.latency_ms = int((time.monotonic() - t0) * 1000)


__all__ = ["RouterSettings", "RoutingResult", "route_cycle", "load_artifact", "certification_gaps", "certification_criteria",
           "accepted_criterion", "artifact_path", "router_root", "MODES", "CERTIFY_MODES", "TAIL_PREFIX"]
