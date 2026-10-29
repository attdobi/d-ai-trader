"""Frozen full-prompt counterfactuals for a shadow router. No config, SQL or HTTP.

Counts cover system + user text, citation indexes, routed-out ID tails, memory
formatting and the client's reasoning-guidance suffix. The default token count
is explicitly a UTF-8/4 heuristic, not a provider token measurement. Rendering
uses the exact cycle's captured graph, health tags and context, never today's DB.
Only counts/hashes leave this module for the comparison ledger.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import base64
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import tempfile

from policy_graph.assembly import assemble, health_tag
from policy_graph.citations import citable_nodes, ltm_index_lines
from policy_safety import blanket_entry_vetoes, opportunity_system_prompt
from .runtime import TAIL_PREFIX

SCHEMA_VERSION = 1
TOKEN_METHOD = "utf8_bytes_div4_estimate"
INDEX_PREFIX = "\n\nGUIDELINE INDEX (id — title):\n"
_BPE_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
_BPE_HASH = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"


@lru_cache(maxsize=2)
def _offline_encoding(cache_dir=None):
    """Construct from a verified local vocabulary; never download at runtime.

    o200k is a declared text-token proxy for the selected model, not its
    undocumented exact framing/tokenizer. Pattern and vocabulary are the
    installed tiktoken 0.14 o200k_base definition. Missing/bad cache falls back.
    """
    try:
        import tiktoken
        cache = str(cache_dir) if cache_dir is not None else str(Path(tempfile.gettempdir()) / "data-gym-cache")
        if not cache:
            return None
        data = (Path(cache) / hashlib.sha1(_BPE_URL.encode()).hexdigest()).read_bytes()
        if hashlib.sha256(data).hexdigest() != _BPE_HASH:
            return None
        ranks = {base64.b64decode(token): int(rank) for token, rank in (line.split() for line in data.splitlines() if line)}
        pattern = "|".join([
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
        ])
        return tiktoken.Encoding(name="dai_offline_o200k_base", pat_str=pattern, mergeable_ranks=ranks,
                                 special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018})
    except (ImportError, OSError, ValueError, TypeError):
        return None


def _sha(system, user):
    return hashlib.sha256((system + "\x00" + user).encode()).hexdigest()


def _tokens(system, user, encoder=None):
    # Two message boundaries are deliberately not invented as an exact tariff.
    if encoder is not None:
        return len(encoder.encode_ordinary(system)) + len(encoder.encode_ordinary(user))
    return math.ceil((len(system.encode()) + len(user.encode())) / 4)


def _system(template, assembled):
    system = template
    if assembled.soul:
        system += "\n\n## AGENT IDENTITY\n" + assembled.soul
    if assembled.strategy_directives:
        if "{strategy_directives}" in system:
            system = system.replace("{strategy_directives}", assembled.strategy_directives)
        else:
            system += "\n\n" + assembled.strategy_directives
    if assembled.memory:
        system += "\n\n## LESSONS FROM EXPERIENCE\n" + assembled.memory
    return opportunity_system_prompt(system)


def _ltm(rows, health, excluded=(), *, tail=None):
    # Same rendering as decider_memory.format_long_term_memory, without loading
    # its config/engine. The actual block is checked byte-for-byte on capture.
    lines = ["# LESSONS (long-term evidence — subordinate to the active policy and opportunity charter):"]
    for row in rows:
        if blanket_entry_vetoes(row.get("content")):
            continue
        ticker = f" ({row['ticker']})" if row.get("ticker") else ""
        content = str(row["content"]).rstrip()
        tag = health_tag(f"DA.ltm.{row['id']}", health)
        lines.append(f"- [{row.get('kind') or 'lesson'}]{ticker} {content}{tag}")
    block = "\n".join(lines) if len(lines) > 1 else ""
    excluded = list(excluded)
    if tail is None and excluded:
        tail = TAIL_PREFIX + ", ".join(excluded[:40]) + (" …" if len(excluded) > 40 else "")
    if tail:
        block = (block + "\n" + tail).strip()
    return "\n\n" + block if block else ""


def _replace_spans(text, replacements):
    ordered = sorted(replacements, key=lambda r: (r[0], r[1]))
    if any(not 0 <= start <= end <= len(text) for start, end, _ in ordered):
        raise ValueError("invalid_prompt_span")
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("overlapping_prompt_spans")
    for start, end, body in reversed(ordered):
        text = text[:start] + body + text[end:]
    return text


@dataclass(frozen=True)
class PromptCapture:
    graph: dict
    actual_system: str
    actual_user: str
    actual_graph_ids: frozenset
    actual_ltm_rows: tuple
    ltm_rows: dict
    ltm_health: dict
    ltm_span: tuple
    index_span: tuple
    actual_ltm_tail: str
    eligible: dict
    client_suffix: str
    model: str
    input_rate: float | None
    token_cache_dir: str | None
    image_manifest: dict | None

    def render(self, selected_ids=None, *, order=None):
        version, context = self.graph["version"], self.graph["context"]
        if selected_ids is None:  # Exact actual-policy reconstruction validation.
            selected_ids = {i for i in self.eligible if i in self.actual_graph_ids}
            selected_ids |= {f"DA.ltm.{r['id']}" for r in self.actual_ltm_rows}
            rows = list(self.actual_ltm_rows)
            actual = True
        else:
            selected_ids = set(selected_ids)
            actual = False
            row_ids = list(order or sorted(selected_ids))
            rows = [r for r in self.actual_ltm_rows if f"DA.ltm.{r['id']}" not in self.eligible]
            rows += [self.ltm_rows[i] for i in row_ids if i in selected_ids and i in self.ltm_rows]
        override = {i: (i in self.actual_graph_ids if actual else i in selected_ids)
                    for i, kind in self.eligible.items() if kind != "ltm"}
        # Pin any noncandidate entry to its actual presence; the scorer may only
        # change its declared candidate universe, not the surrounding policy.
        for ident, node in version.nodes.items():
            if node.node_type == "entry" and ident not in override:
                override[ident] = ident in self.actual_graph_ids
        if not any(kind != "ltm" for kind in self.eligible.values()):
            # An LTM-only comparison changes no graph entries. Reuse the exact
            # actual override so an unrelated dropped-diary tail does not gain
            # the "routed out" wording merely because we counted memory rows.
            override = self.graph.get("override")
        assembled = assemble(version, context, health=self.graph["health"],
                             override=self.graph.get("override") if actual else override or None)
        system = _system(self.graph["template"], assembled) + self.client_suffix
        graph_ids = {s.node_id for s in assembled.served}
        index = [f"{i} — {title}" for i, title in citable_nodes(version)
                 if i in graph_ids or i.split(".")[1:2] == ["code"]]
        index += ltm_index_lines(rows)
        excluded = [] if actual else [i for i, kind in self.eligible.items() if kind == "ltm" and i not in selected_ids]
        block = _ltm(rows, self.ltm_health, excluded,
                     tail=self.actual_ltm_tail if actual else None)
        user = _replace_spans(self.actual_user, [(*self.ltm_span, block),
                             (*self.index_span, INDEX_PREFIX + "\n".join(index) if index else "")])
        return system, user


def capture_prompt(*, graph, system_prompt, user_prompt, actual_graph_ids, actual_ltm_rows,
                   ltm_rows, ltm_health, ltm_span, index_span, eligible, model,
                   input_rate=None, client_suffix="", actual_ltm_tail="", token_cache_dir=None,
                   image_manifest=None):
    """Freeze an assembly, rejecting incompatible/ambiguous reconstruction."""
    if not graph or ltm_span is None or index_span is None:
        raise ValueError("missing_frozen_assembly")
    rate = input_rate if isinstance(input_rate, (int, float)) and not isinstance(input_rate, bool) else None
    rate = float(rate) if rate is not None and math.isfinite(rate) and rate > 0 else None
    capture = PromptCapture(deepcopy(graph), system_prompt + client_suffix, user_prompt,
        frozenset(actual_graph_ids), tuple(deepcopy(actual_ltm_rows)), deepcopy(ltm_rows), deepcopy(ltm_health),
        tuple(ltm_span), tuple(index_span), str(actual_ltm_tail), dict(eligible), str(client_suffix), str(model), rate,
        str(token_cache_dir) if token_cache_dir is not None else None, deepcopy(image_manifest))
    if capture.render() != (capture.actual_system, capture.actual_user):
        raise ValueError("frozen_assembly_does_not_match_actual_prompt")
    return capture


def unavailable(note="No frozen full-prompt capture for this comparison"):
    return {"schema_version": SCHEMA_VERSION, "status": "unavailable", "note": note,
            "realized_input_savings_usd": 0.0, "quality_status": "not_evaluated"}


def measure(capture, result):
    """Count three identical-format variants off-thread; never activates routing."""
    if capture is None:
        return unavailable()
    if result.status != "ok" or result.selection is None:
        return unavailable("Router did not return a usable selection")
    selected = [d.node_id for d in result.selection.included]
    if set(result.nodes) != set(capture.eligible):
        return unavailable("Frozen candidate universe does not match the router response")
    actual = (capture.actual_system, capture.actual_user)
    full = capture.render(set(capture.eligible))
    routed = capture.render(set(selected), order=selected)
    prompts = {"actual_served": actual, "all_candidates": full, "decisions_selected": routed}
    encoder = _offline_encoding(capture.token_cache_dir)
    method = "o200k_base_text_estimate" if encoder is not None else TOKEN_METHOD
    counts = {key: _tokens(*value, encoder=encoder) for key, value in prompts.items()}
    saved = counts["actual_served"] - counts["decisions_selected"]
    gross = saved * capture.input_rate / 1_000_000 if capture.input_rate is not None else None
    fee = result.cost_usd
    image_count = int((capture.image_manifest or {}).get("image_count") or 0)
    text_reduction = saved * 100 / counts["actual_served"] if counts["actual_served"] else None
    return {"schema_version": SCHEMA_VERSION, "status": "estimated", "capture_basis": "frozen_full_prompt_v1",
        "token_method": method, "token_estimates": counts,
        "token_scope": "text_only" if image_count else "system_and_user_text",
        "image_count": image_count, "image_input_tokens": None if image_count else 0,
        "image_identity_hash": (capture.image_manifest or {}).get("snapshot_hash"),
        "images_preserved_across_variants": True,
        "characters": {key: sum(map(len, value)) for key, value in prompts.items()},
        "prompt_hashes": {key: _sha(*value) for key, value in prompts.items()},
        "decider_model": capture.model, "decider_model_basis": "configured_primary_request_model",
        "provider_input_tokens": None, "input_rate_usd_per_million": capture.input_rate,
        "potential_input_tokens_saved": saved,
        "potential_input_reduction_pct": None if image_count else text_reduction,
        "text_input_reduction_pct": text_reduction,
        "gross_input_savings_usd_uncached_estimate": gross, "router_cost_usd": fee,
        "net_input_savings_usd_uncached_estimate": gross - fee if gross is not None and fee is not None else None,
        "cache_adjusted_savings_usd": None, "realized_input_savings_usd": 0.0,
        "shadow_incremental_cost_usd": fee, "quality_status": "not_evaluated",
        "note": "Shadow serves the actual prompt unchanged. Local text token counts are estimates, not provider-billed tokens or message framing. Supplied images are identical across all three Decider variants and never counted as removed context; their token profile is not inferred from pixels or base64 length. Decider model is the configured primary request model; provider fallbacks/retries are not measured here. Dollar potential assumes uncached standard text input pricing and subtracts the complete recorded router fee, including its image input. Cache effects, completion/reasoning and quality changes are unknown."}
