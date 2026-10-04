"""Optional Jev-like escalation: a yes/no question to a local chat model for the nodes the base model is unsure of.

For each routable node whose base p falls inside the uncertain band (default 0.2–0.8), most uncertain
first, the tier asks the chat model on the same OpenAI-compatible endpoint (LM Studio; the 2×RTX 3090
host joins over LM Link and exposes its chat models there):

    "Will this guideline be needed for this cycle's decisions?"  → yes | no

P(yes) is read from the first token's logprobs when the server returns them (normalized over the
yes/no mass); otherwise from a constrained JSON answer {"p": number}. The tier's p is combined with
the base p by a weighted average in logit space. The tier is optional and auto-detected: it is
skipped silently, with one log line, when no model is configured, the configured model is not
loaded on the endpoint, or the hard per-cycle budget (15 s) is spent. It never raises.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Callable, Optional, Sequence

from .embed import DEFAULT_BASE_URL, call_with_deadline, http_get_json, http_post_json

QUESTION = "Will this guideline be needed for this cycle's decisions?"
SYSTEM = ("You route guidelines for a cautious swing-trading agent. Given this cycle's market context and one "
          "guideline, answer whether the agent will need that guideline to make or justify this cycle's "
          "buy / sell / hold decisions. Answer with exactly one word: yes or no.")
SYSTEM_JSON = ("You route guidelines for a cautious swing-trading agent. Given this cycle's market context and one "
               "guideline, estimate the probability that the agent will need that guideline to make or justify "
               "this cycle's decisions. Reply only with JSON {\"p\": <number between 0 and 1>}.")
_NUM_RE = re.compile(r"\"?p\"?\s*[:=]\s*([01](?:\.\d+)?|\.\d+)")


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(z, 35.0), -35.0)))


def combine(p_base: float, p_llm: float, weight: float = 0.5) -> float:
    """Weighted average in logit space (weight = the LLM's share)."""
    w = min(max(float(weight), 0.0), 1.0)
    return _sigmoid((1 - w) * _logit(p_base) + w * _logit(p_llm))


def p_yes_from_logprobs(resp: dict) -> Optional[float]:
    """P(yes) from the first generated token's top logprobs (OpenAI chat shape), or None."""
    try:
        content = resp["choices"][0]["logprobs"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not content:
        return None
    first = content[0] or {}
    cands = list(first.get("top_logprobs") or [])
    if first.get("token") is not None and first.get("logprob") is not None:
        cands.append({"token": first.get("token"), "logprob": first.get("logprob")})
    yes = no = 0.0
    seen = set()
    for c in cands:
        tok = str(c.get("token") or "").strip().strip(".!\"'").lower()
        key = (tok, round(float(c.get("logprob", -99.0)), 6))
        if key in seen:
            continue
        seen.add(key)
        try:
            prob = math.exp(float(c.get("logprob")))
        except (TypeError, ValueError):
            continue
        if tok in ("yes", "y"):
            yes += prob
        elif tok in ("no", "n"):
            no += prob
    if yes + no <= 0:
        return None
    return yes / (yes + no)


def p_from_json_answer(resp: dict) -> Optional[float]:
    try:
        text = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    text = str(text or "").strip()
    val = None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and obj.get("p") is not None:
            val = float(obj["p"])
    except (ValueError, TypeError):
        m = _NUM_RE.search(text)
        if m:
            val = float(m.group(1))
    if val is None:
        low = text.lower()
        if low.startswith("yes"):
            val = 0.9
        elif low.startswith("no"):
            val = 0.1
    if val is None or not (0.0 <= val <= 1.0):
        return None
    return val


class LLMTier:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = "", *, transport: Optional[Callable] = None,
                 get_transport: Optional[Callable] = None, budget_s: float = 15.0, band: tuple = (0.2, 0.8),
                 weight: float = 0.5, max_nodes: int = 12, per_call_s: float = 8.0, log: Callable = print):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = (model or "").strip()
        self.transport = transport or http_post_json
        self.get_transport = get_transport or http_get_json
        self.budget_s = float(budget_s)
        self.band = (float(band[0]), float(band[1]))
        self.weight = float(weight)
        self.max_nodes = int(max_nodes)
        self.per_call_s = float(per_call_s)
        self.log = log
        self._logprobs_ok: Optional[bool] = None
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------ availability
    def available(self, timeout: float = 2.0) -> bool:
        """True when a model is configured AND loaded on the endpoint (GET /models, cached)."""
        if not self.model:
            return False
        if self._available is None:
            try:
                resp = call_with_deadline(lambda: self.get_transport(f"{self.base_url}/models", timeout), timeout)
                ids = {str(m.get("id")) for m in (resp or {}).get("data") or [] if isinstance(m, dict)}
                self._available = self.model in ids
            except Exception:       # noqa: BLE001 — endpoint down = tier unavailable
                self._available = False
        return bool(self._available)

    # ------------------------------------------------------------------ one question
    def _messages(self, context_text: str, node_id: str, node_text: str, system: str) -> list:
        return [{"role": "system", "content": system},
                {"role": "user", "content": f"CYCLE CONTEXT:\n{context_text[:2500]}\n\nGUIDELINE {node_id}:\n"
                                            f"{node_text[:1200]}\n\n{QUESTION}"}]

    def ask(self, context_text: str, node_id: str, node_text: str, timeout: float) -> Optional[float]:
        """P(needed) for one node within `timeout` seconds in total: the logprobs probe and the JSON fallback
        share that window (the fallback gets only what the probe left; None when that is under 0.2 s)."""
        t0 = time.monotonic()
        if self._logprobs_ok is not False:
            payload = {"model": self.model, "messages": self._messages(context_text, node_id, node_text, SYSTEM),
                       "temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 10}
            resp = call_with_deadline(lambda: self.transport(f"{self.base_url}/chat/completions", payload, timeout), timeout)
            p = p_yes_from_logprobs(resp)
            if p is not None:
                self._logprobs_ok = True
                return p
            self._logprobs_ok = False          # the server ignores logprobs: use the JSON form from now on
            timeout = timeout - (time.monotonic() - t0)
            if timeout <= 0.2:
                return None                    # refine() moves on and stops on its own budget check
        payload = {"model": self.model, "messages": self._messages(context_text, node_id, node_text, SYSTEM_JSON),
                   "temperature": 0, "max_tokens": 20,
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": "p_needed", "strict": True,
                       "schema": {"type": "object", "properties": {"p": {"type": "number", "minimum": 0, "maximum": 1}},
                                  "required": ["p"], "additionalProperties": False}}}}
        resp = call_with_deadline(lambda: self.transport(f"{self.base_url}/chat/completions", payload, timeout), timeout)
        return p_from_json_answer(resp)

    # ------------------------------------------------------------------ one cycle
    def refine(self, context_text: str, items: Sequence) -> tuple:
        """items = [(node_id, text, p_base)] → ({node_id: p_combined}, info). Never raises."""
        info = {"asked": 0, "answered": 0, "skipped": None, "elapsed_ms": 0, "logprobs": None}
        if not self.model:
            info["skipped"] = "no chat model configured"
            return {}, info
        start = time.monotonic()
        if not self.available():
            info["skipped"] = f"chat model {self.model!r} not loaded on {self.base_url}"
            self.log(f"🧭 Router LLM tier skipped: {info['skipped']}")
            return {}, info
        lo, hi = self.band
        unsure = sorted((it for it in items if lo <= float(it[2]) <= hi), key=lambda it: abs(float(it[2]) - 0.5))
        out = {}
        for nid, text, p_base in unsure[: self.max_nodes]:
            remaining = self.budget_s - (time.monotonic() - start)
            if remaining <= 0.2:
                info["skipped"] = f"budget of {self.budget_s:.0f}s spent after {info['answered']} answers"
                self.log(f"🧭 Router LLM tier stopped: {info['skipped']}")
                break
            info["asked"] += 1
            try:
                p_llm = self.ask(context_text, nid, text, min(self.per_call_s, remaining))
            except Exception as exc:     # noqa: BLE001 — timeout / HTTP error: stop asking this cycle
                info["skipped"] = f"{type(exc).__name__}: {exc}"
                self.log(f"🧭 Router LLM tier stopped after {info['answered']} answers: {info['skipped']}")
                break
            if p_llm is None:
                continue
            info["answered"] += 1
            out[nid] = combine(float(p_base), p_llm, self.weight)
        info["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        info["logprobs"] = self._logprobs_ok
        return out, info


__all__ = ["LLMTier", "combine", "p_yes_from_logprobs", "p_from_json_answer", "QUESTION"]
