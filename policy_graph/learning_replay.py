"""Paired policy replays against frozen Decider inputs; no trading or activation.

``preview_comparison`` validates everything without a model call or database write.
``run_comparison`` calls an explicitly supplied runner twice per saved input. The
runner receives only the captured prompts and model settings, never outcome labels.
Its return value must be ``{reply, model, reasoning_effort, usage?, cost_usd?}``.

Two assembly modes are intentionally distinct:
* captured_subgraph_edits: retain the captured selected guideline set, metadata,
  code instructions and context; patch only compatible edits to stored node bodies.
* full_policy: insert ALL stored policy guidelines for BOTH policies and rebuild
  their citation indexes. This supports additions/removals but is not a simulation
  of production subgraph routing. Captured health annotations remain frozen.

Stored prompts/replies stay in local audit tables. Public results expose action
differences and paper outcomes, never prompts, holdings balances or raw replies.
No config import, environment read, HTTP client, model fallback or retry lives here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time

from sqlalchemy import text

from .decompose import decompose_row
from .model import RowMeta

MODES = ("captured_subgraph_edits", "full_policy")
FIELD_KEYS = {"soul": "soul", "directives": "strategy_directives", "memory": "memory"}
TEMPLATES = ("system_prompt", "user_prompt_template")
INDEX_MARKER = "GUIDELINE INDEX (id — title):\n"
TAG_RE = re.compile(r"⟨(DA\.[a-z0-9_.]+)(?:\s*·[^⟩]*)?⟩")
INDEX_RE = re.compile(r"^(DA\.[a-z0-9_.]+) — ([^\n]*)$", re.M)
ACTIONS = {"BUY", "PASS", "HOLD", "SELL"}
MIN_COMPARABLE = 5
DESTINATION = "https://api.openai.com/v1/chat/completions"
CREDENTIAL_RE = re.compile(
    r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
    r"\bAuthorization\s*:\s*Bearer\s+\S+|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", re.I)


def _credential_guard(values):
    if any(CREDENTIAL_RE.search(str(value or "")) for value in values):
        raise ReplayError("credential-shaped material found; inspect the local saved input before replay")

DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_learning_replays (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    incumbent_version INTEGER NOT NULL,
    candidate_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT,
    assembly_mode TEXT NOT NULL,
    cohort_hash TEXT NOT NULL,
    frozen_json TEXT NOT NULL,
    summary_json TEXT NOT NULL
)
"""
DDL_CALLS_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_learning_replay_calls (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    replay_id INTEGER NOT NULL,
    source_input_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT,
    request_hash TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    raw_reply TEXT,
    result_json TEXT NOT NULL,
    UNIQUE (replay_id, source_input_id, side)
)
"""
DDL_CASES_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_learning_replay_cases (
    id SERIAL PRIMARY KEY,
    config_hash VARCHAR(50) NOT NULL,
    replay_id INTEGER NOT NULL,
    source_input_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    case_json TEXT NOT NULL,
    UNIQUE (replay_id, source_input_id, ticker)
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
DDL_CALLS_SQLITE = DDL_CALLS_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
DDL_CASES_SQLITE = DDL_CASES_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")


class ReplayError(ValueError):
    """The frozen input or proposed comparison is not safe to replay."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


def _hash(value):
    return hashlib.sha256((value if isinstance(value, str) else _json(value)).encode("utf-8")).hexdigest()


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def ensure_schema(engine):
    postgres = engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        for pg, sq in ((DDL_POSTGRES, DDL_SQLITE), (DDL_CALLS_POSTGRES, DDL_CALLS_SQLITE),
                       (DDL_CASES_POSTGRES, DDL_CASES_SQLITE)):
            conn.execute(text(pg if postgres else sq))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_learning_replays_config ON policy_learning_replays (config_hash, id)"))


def _row(engine, config_hash, version):
    with engine.connect() as conn:
        found = conn.execute(text("""
            SELECT id, version, system_prompt, user_prompt_template, soul,
                   strategy_directives, memory, created_at
            FROM prompt_versions
            WHERE config_hash=:h AND agent_type='DeciderAgent' AND version=:v
            ORDER BY id DESC LIMIT 1
        """), {"h": config_hash, "v": int(version)}).mappings().first()
    if not found:
        raise ReplayError(f"Decider policy v{version} is unavailable for this configuration")
    return dict(found)


def _nodes(row):
    build = decompose_row("DeciderAgent", "replay", int(row["version"]), row,
                          meta=RowMeta(int(row["id"]), row.get("created_at"), "replay"),
                          inherited={}, code_nodes=[], ltm_nodes=[], is_margin_account=False)
    return {node.id: node for node in build.nodes if node.field in FIELD_KEYS.values()}, build


def _policy_hash(row):
    return _hash({key: row.get(key) for key in (*TEMPLATES, *FIELD_KEYS.values())})


def _source_inputs(engine, config_hash, ids):
    if not isinstance(ids, (list, tuple)) or not ids or len(ids) > 20:
        raise ReplayError("choose between 1 and 20 exact saved input IDs")
    clean = []
    for value in ids:
        if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
            raise ReplayError("source input IDs must be positive integers")
        if int(value) not in clean:
            clean.append(int(value))
    sources = []
    with engine.connect() as conn:
        for ident in clean:
            row = conn.execute(text("SELECT * FROM decider_inputs WHERE id=:id AND config_hash=:h AND call_kind='decide'"),
                               {"id": ident, "h": config_hash}).mappings().first()
            if row is None:
                raise ReplayError(f"saved Decider input {ident} is unavailable for this configuration")
            source = dict(row)
            if source.get("prompt_version") is None or not source.get("system_prompt") or not source.get("user_prompt"):
                raise ReplayError(f"saved input {ident} lacks exact prompts or policy version")
            sources.append(source)
    if len({int(s["prompt_version"]) for s in sources}) != 1:
        raise ReplayError("one comparison must use a single incumbent policy version")
    return sources


def _tags(source):
    return {m.group(1): m.group(0) for m in TAG_RE.finditer(source["system_prompt"])}


def _replace_spans(source, replacements):
    """Locate against the original string, then splice; replacements cannot cascade."""
    system = source["system_prompt"]
    spans = []
    for key, replacement in replacements.items():
        original = source.get("policy_" + key) or ""
        if not original:
            if replacement:
                raise ReplayError(f"captured {key} is empty; no unambiguous insertion span exists")
            continue
        if system.count(original) != 1:
            raise ReplayError(f"captured {key} must occur exactly once in the saved system prompt")
        start = system.index(original)
        spans.append((start, start + len(original), replacement))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ReplayError("captured policy fields overlap")
    for start, end, replacement in reversed(spans):
        system = system[:start] + replacement + system[end:]
    return system


def _index(user, entries, *, replace_all):
    """Replace only explicit policy index lines, preserving frozen code/LTM/context."""
    occurrences = user.count(INDEX_MARKER)
    if not occurrences:
        if TAG_RE.search("\n".join(entries)):
            raise ReplayError("annotated fields require a captured guideline index")
        # A flat prompt predating citation logging can remain flat. New index
        # material is not silently appended to its original context.
        return user
    if occurrences != 1:
        raise ReplayError("saved guideline index is ambiguous")
    head, tail = user.split(INDEX_MARKER)
    matches = list(INDEX_RE.finditer(tail))
    if not matches:
        raise ReplayError("saved guideline index has no verifiable entries")
    ids = [m.group(1) for m in matches]
    if len(set(ids)) != len(ids):
        raise ReplayError("saved guideline index has duplicate IDs")
    if replace_all:
        # This is a captured suffix, never a regenerated current-code index.
        # Do not drop code/long-term-memory citations when changing policy IDs.
        preserved = [(m.group(1), m.group(2)) for m in matches
                     if not m.group(1).startswith(("DA.directives", "DA.soul", "DA.memory"))]
        leftover = INDEX_RE.sub("", tail).strip()
        if leftover:
            raise ReplayError("non-index text follows the captured index; exact rebuilding is unavailable")
        combined = list(entries.items()) + preserved
        return head + INDEX_MARKER + "\n".join(f"{ident} — {title}" for ident, title in combined)
    def update(match):
        ident = match.group(1)
        return f"{ident} — {entries.get(ident, match.group(2))}"
    return head + INDEX_MARKER + INDEX_RE.sub(update, tail)


def _render_full(row, source):
    nodes, build = _nodes(row)
    tags = _tags(source)
    fields, entries = {}, {}
    annotated = bool(tags)
    for key, field in FIELD_KEYS.items():
        # NULL/empty fields may be inherited from disk; present-day defaults are
        # not evidence of the historical effective policy. Use captured field
        # only when the *stored* field is unchanged (checked by caller).
        if not row.get(field):
            fields[key] = source.get("policy_" + key) or ""
            continue
        parts = []
        for ident in build.compile_order.get(field, []):
            node = nodes[ident]
            body = node.body
            if body.strip() and node.node_type in ("section", "rule", "lesson", "entry", "reminder", "identity", "note"):
                entries[ident] = node.title.replace("\n", " ")
            if annotated and node.node_type in ("rule", "lesson", "entry", "section", "note", "identity", "reminder") and body.strip():
                body = body.rstrip() + " " + tags.get(ident, f"⟨{ident}⟩")
                after = node.sep_after or "\n"
            else:
                after = node.sep_after
            parts.append(node.sep_before + body + after)
        fields[key] = "".join(parts).strip("\n")
    # Inherited captured fields can contain guidelines absent from stored rows.
    for match in INDEX_RE.finditer(source["user_prompt"]):
        ident = match.group(1)
        for key, field in FIELD_KEYS.items():
            if not row.get(field) and TAG_RE.search(fields[key]) and ident in {m.group(1) for m in TAG_RE.finditer(fields[key])}:
                entries[ident] = match.group(2)
    return fields, entries


def _patch_captured(source, incumbent, candidate):
    old_nodes, _ = _nodes(incumbent)
    new_nodes, _ = _nodes(candidate)
    if set(old_nodes) != set(new_nodes):
        raise ReplayError("guideline additions/removals require full_policy replay for both policies")
    fields = {key: source.get("policy_" + key) or "" for key in FIELD_KEYS}
    changes = []
    for key, field in FIELD_KEYS.items():
        if incumbent.get(field) == candidate.get(field):
            continue
        if not incumbent.get(field) or not candidate.get(field):
            raise ReplayError("changed inherited/empty fields require an exact explicit policy snapshot")
        captured = fields[key]
        if not TAG_RE.search(captured):
            if captured != str(incumbent[field]).strip("\n"):
                raise ReplayError(f"flat captured {key} differs from its stored policy")
            fields[key] = str(candidate[field]).strip("\n")
            changes.extend(i for i, n in new_nodes.items() if n.field == field and n.body != old_nodes[i].body)
            continue
        spans = []
        for ident, old in old_nodes.items():
            new = new_nodes[ident]
            if old.field != field or old.body == new.body:
                continue
            marker = re.search(r"⟨" + re.escape(ident) + r"(?:\s*·[^⟩]*)?⟩", captured)
            if marker is None:
                # Freeze selection: a change to a guideline that was not served
                # has no effect in this declared assembly mode.
                continue
            body = old.body.rstrip()
            end = marker.start()
            if end and captured[end - 1] == " ":
                end -= 1
            start = end - len(body)
            if start < 0 or captured[start:end] != body:
                raise ReplayError(f"captured body for {ident} differs from the stored policy")
            spans.append((start, end, new.body.rstrip()))
            changes.append(ident)
        for start, end, replacement in sorted(spans, reverse=True):
            captured = captured[:start] + replacement + captured[end:]
        fields[key] = captured
    return fields, {i: n.title.replace("\n", " ") for i, n in new_nodes.items()}, changes


def _validate_incumbent_capture(source, incumbent):
    """Prove every served stored body still describes the captured incumbent.

    Checking only nodes edited by the candidate misses a rewritten historical
    row when the same rewrite also appears in the candidate. Such a row hash
    would describe different bytes from the actual incumbent replay. Health
    suffixes are frozen metadata, so match canonical bodies immediately before
    their captured IDs without querying present-day health.
    """
    nodes, _ = _nodes(incumbent)
    for key, field in FIELD_KEYS.items():
        raw = incumbent.get(field)
        captured = source.get("policy_" + key) or ""
        if not raw:
            # No stored historical body exists for inherited defaults. Those
            # fields remain captured/frozen on both sides; present-day disk files
            # are deliberately not used to manufacture historical evidence.
            continue
        markers = list(TAG_RE.finditer(captured))
        if not markers:
            if captured != str(raw).strip("\n"):
                raise ReplayError(f"captured incumbent {key} differs from the stored policy")
            continue
        seen = set()
        for marker in markers:
            ident = marker.group(1)
            node = nodes.get(ident)
            if ident in seen or node is None or node.field != field:
                raise ReplayError("captured incumbent guideline IDs differ from the stored policy")
            seen.add(ident)
            body = node.body.rstrip()
            end = marker.start()
            if end and captured[end - 1] == " ":
                end -= 1
            start = end - len(body)
            if not body or start < 0 or captured[start:end] != body:
                raise ReplayError(f"captured incumbent body for {ident} differs from the stored policy")
        # Field preambles are always served by assembly but do not receive an ID
        # suffix. Verify their verbatim slice too, rather than exempting them
        # because the surrounding leaf guidelines carry all the visible tags.
        for node in nodes.values():
            if node.field == field and node.node_type == "field" and node.body.strip():
                if captured.count(node.body.strip("\n")) != 1:
                    raise ReplayError(f"captured incumbent {key} preamble differs from the stored policy")


def _case_rows(engine, config_hash, sources, cases):
    ids = {int(s["id"]) for s in sources}
    if cases is None:
        try:
            from .opportunities import list_cases
            cases = list_cases(engine, config_hash, days=3650, limit=10000)
        except Exception:
            cases = []
    found = []
    seen = set()
    for case in cases or []:
        if case.get("config_hash") != config_hash or case.get("input_id") not in ids:
            continue
        key = (int(case["input_id"]), str(case.get("ticker") or "").upper())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        found.append(copy.deepcopy(case))
    # Old saved inputs can still support action comparisons; reconstructed cases
    # must never acquire the prospective ledger's recall eligibility.
    for source in sources:
        context = source.get("context_json") or "{}"
        try:
            context = json.loads(context) if isinstance(context, str) else context
        except (TypeError, ValueError):
            context = {}
        tickers = set(t for key in ("watchlist", "holdings", "news", "entities", "trend")
                      for t in (context.get(key) or []) if isinstance(t, str))
        for ticker in sorted(tickers):
            ticker = ticker.upper()
            key = (int(source["id"]), ticker)
            if key not in seen and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
                seen.add(key)
                found.append({"id": None, "config_hash": config_hash, "input_id": source["id"],
                              "run_id": source.get("run_id"), "prompt_version": source["prompt_version"],
                              "ticker": ticker, "observed_at": _iso(source.get("decided_at")),
                              "coverage": "reconstructed_context", "eligible_for_recall": False,
                              "action": "NOT_ASSESSED", "features": {"regime": context.get("regime")},
                              "outcomes": {}})
    return sorted(found, key=lambda c: (int(c["input_id"]), c["ticker"]))


def _prepare(engine, config_hash, source_input_ids, candidate_version, *, assembly_mode="captured_subgraph_edits",
             candidate_policy=None, model=None, reasoning_effort=None, cases=None, outcome_spec=None, max_calls=40):
    if assembly_mode not in MODES:
        raise ReplayError("unknown replay assembly mode")
    sources = _source_inputs(engine, config_hash, source_input_ids)
    if len(sources) * 2 > max(0, min(int(max_calls), 40)):
        raise ReplayError("comparison exceeds the explicit model-call budget")
    incumbent = _row(engine, config_hash, int(sources[0]["prompt_version"]))
    candidate = _row(engine, config_hash, candidate_version)
    _credential_guard(candidate.get(key) for key in (*TEMPLATES, *FIELD_KEYS.values()))
    for source in sources:
        _credential_guard(source.get(key) for key in ("system_prompt", "user_prompt", "policy_soul", "policy_directives", "policy_memory"))
    if int(candidate["version"]) == int(incumbent["version"]):
        raise ReplayError("choose distinct incumbent and candidate versions")
    for key in TEMPLATES:
        if incumbent.get(key) != candidate.get(key):
            raise ReplayError(f"{key} changed; exact context-preserving replay is unavailable")
    for key, field in FIELD_KEYS.items():
        if (not incumbent.get(field) or not candidate.get(field)) and incumbent.get(field) != candidate.get(field):
            raise ReplayError(f"changed inherited {key} is not reconstructable from stored rows")
    source_settings = {(s.get("model"), s.get("reasoning_effort")) for s in sources}
    if model is None and len(source_settings) != 1:
        raise ReplayError("saved models/efforts differ; choose one explicit model and reasoning effort for both sides")
    chosen_model = model or sources[0].get("model")
    chosen_effort = reasoning_effort if model is not None else sources[0].get("reasoning_effort")
    if not chosen_model or not isinstance(chosen_model, str):
        raise ReplayError("an explicit replay model is required")
    if chosen_effort not in (None, "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
        raise ReplayError("invalid reasoning effort")
    requests, edits = [], set()
    for source in sources:
        if TAG_RE.search(source["system_prompt"]) and source["user_prompt"].count(INDEX_MARKER) != 1:
            raise ReplayError("annotated captured policy requires one exact guideline index")
        original = {key: source.get("policy_" + key) or "" for key in FIELD_KEYS}
        # Every saved span must still match exactly, even if this candidate does
        # not happen to change that field. This also detects code/assembly drift.
        _replace_spans(source, original)
        _validate_incumbent_capture(source, incumbent)
        if assembly_mode == "full_policy":
            old_fields, old_index = _render_full(incumbent, source)
            new_fields, new_index = _render_full(candidate, source)
            incumbent_system = _replace_spans(source, old_fields)
            incumbent_user = _index(source["user_prompt"], old_index, replace_all=True)
            candidate_user = _index(source["user_prompt"], new_index, replace_all=True)
            old_nodes, _ = _nodes(incumbent)
            new_nodes, _ = _nodes(candidate)
            edits.update(i for i in set(old_nodes) | set(new_nodes)
                         if i not in old_nodes or i not in new_nodes or old_nodes[i].body != new_nodes[i].body)
        else:
            new_fields, new_index, changed = _patch_captured(source, incumbent, candidate)
            edits.update(changed)
            incumbent_system, incumbent_user = source["system_prompt"], source["user_prompt"]
            candidate_user = _index(source["user_prompt"], new_index, replace_all=False)
        if candidate_policy is not None:
            # Explicit render snapshots must describe this target row and cannot
            # silently change templates or add an unverified citation vocabulary.
            if not isinstance(candidate_policy, dict) or any(candidate_policy.get(k) != candidate.get(k) for k in TEMPLATES):
                raise ReplayError("explicit candidate policy must include both exact target templates")
            supplied = candidate_policy.get("fields")
            if supplied != new_fields:
                raise ReplayError("explicit candidate render does not match the validated frozen assembly")
        candidate_system = _replace_spans(source, new_fields)
        for side, system, user in (("incumbent", incumbent_system, incumbent_user),
                                   ("candidate", candidate_system, candidate_user)):
            request = {"config_hash": config_hash, "source_input_id": int(source["id"]), "side": side, "system_prompt": system,
                       "user_prompt": user, "model": chosen_model, "reasoning_effort": chosen_effort}
            request["request_hash"] = _hash(request)
            requests.append(request)
    case_rows = _case_rows(engine, config_hash, sources, cases)
    if not case_rows:
        raise ReplayError("no audited candidate cases or captured context tickers are available for these inputs")
    outcome_spec = copy.deepcopy(outcome_spec or {"horizon": 3, "basis": "prospective_ledger_fixed_horizon"})
    if outcome_spec.get("horizon") not in (1, 3, 5):
        raise ReplayError("paper outcome horizon must be 1, 3 or 5 sessions")
    frozen = {"source_input_ids": [int(s["id"]) for s in sources], "source_hashes": {
        str(s["id"]): _hash({k: s.get(k) for k in ("system_prompt", "user_prompt", "model", "reasoning_effort", "prompt_version",
            "policy_soul", "policy_directives", "policy_memory", "context_json", "ltm_ids", "run_id", "decided_at", "raw_reply")}) for s in sources},
        "incumbent_policy_hash": _policy_hash(incumbent), "candidate_policy_hash": _policy_hash(candidate),
        "candidate_created_at": _iso(candidate.get("created_at")), "outcome_spec": outcome_spec,
        "cases": case_rows, "request_hashes": [r["request_hash"] for r in requests], "changed_ids": sorted(edits)}
    return {"incumbent_version": incumbent["version"], "candidate_version": candidate["version"],
            "model": chosen_model, "reasoning_effort": chosen_effort, "assembly_mode": assembly_mode,
            "sources": sources, "requests": requests, "frozen": frozen, "cohort_hash": _hash(frozen)}


def preview_comparison(engine, config_hash, source_input_ids, candidate_version, **kwargs):
    """Read-only compatibility DTO. No runner, table creation or prompt exposure."""
    try:
        prepared = _prepare(engine, config_hash, source_input_ids, candidate_version, **kwargs)
    except ReplayError as exc:
        return {"compatible": False, "errors": [str(exc)], "model_calls": 0}
    frozen = prepared["frozen"]
    return {"compatible": True, "errors": [], "model_calls": len(prepared["requests"]),
            "source_input_ids": frozen["source_input_ids"], "case_count": len(frozen["cases"]),
            "prospective_case_count": sum(bool(c.get("eligible_for_recall")) for c in frozen["cases"]),
            "incumbent_version": prepared["incumbent_version"], "candidate_version": prepared["candidate_version"],
            "assembly_mode": prepared["assembly_mode"], "model": prepared["model"],
            "reasoning_effort": prepared["reasoning_effort"], "cohort_hash": prepared["cohort_hash"],
            "changed_ids": frozen["changed_ids"], "outcome_spec": frozen["outcome_spec"], "destination": DESTINATION,
            "note": "Retrospective policy replay; no orders or activation. Full-policy mode compares all stored guidelines on both sides, not production routing."}


def parse_actions(reply):
    """Strict JSON only. Missing/unknown actions remain unassessed, never PASS."""
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except ValueError as exc:
            raise ReplayError("model reply is not JSON") from exc
    if not isinstance(reply, dict) or not isinstance(reply.get("decisions"), list):
        raise ReplayError("model reply must contain a decisions array")
    found = {}
    for kind in ("decisions", "considered"):
        rows = reply.get(kind, [])
        if not isinstance(rows, list):
            raise ReplayError(f"model {kind} must be an array")
        for row in rows:
            if not isinstance(row, dict):
                raise ReplayError("model actions must be objects")
            ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
                continue
            action = str(row.get("action") or row.get("verdict") or "").upper().strip()
            action = {"REJECT": "PASS", "REJECTED": "PASS", "SKIP": "PASS", "DECLINE": "PASS"}.get(action, action)
            if action not in ACTIONS:
                continue
            # The actual per-ticker decision takes precedence over its narrative
            # audit entry. Conflicting duplicate decisions are invalid.
            if ticker in found:
                if kind == "decisions" and found[ticker]["action"] != action:
                    raise ReplayError("model has conflicting duplicate decisions")
                continue
            cited = row.get("cited") or []
            if not isinstance(cited, list):
                cited = []
            found[ticker] = {"action": action, "reason": str(row.get("reason") or row.get("why") or "")[:1200],
                             "cited": [s for s in cited if isinstance(s, str) and re.fullmatch(r"DA\.[a-z0-9_.]+", s)][:20]}
    return found


def _call(runner, request):
    started = time.monotonic()
    result = {"status": "error", "actions": {}, "cost_usd": None, "usage": {}, "error": None}
    raw = None
    try:
        # Copy prevents an injected client from mutating the frozen comparison.
        answer = runner(copy.deepcopy(request))
        if not isinstance(answer, dict) or "reply" not in answer:
            raise ReplayError("runner must return reply and exact model settings")
        raw = answer["reply"]
        cost = answer.get("cost_usd")
        if cost is not None and (not isinstance(cost, (float, int)) or isinstance(cost, bool) or not math.isfinite(cost) or cost < 0):
            raise ReplayError("runner cost must be finite and nonnegative")
        result.update(cost_usd=cost, usage=answer.get("usage") if isinstance(answer.get("usage"), dict) else {})
        actual = answer.get("model")
        result["actual_model"] = actual
        # The provider may resolve an alias to its dated snapshot. Accept that
        # resolution, then require ONE identical actual model across the batch.
        same_model = isinstance(actual, str) and (actual == request["model"] or bool(
            re.fullmatch(re.escape(request["model"]) + r"-\d{4}-\d{2}-\d{2}", actual)))
        if not same_model or answer.get("reasoning_effort") != request["reasoning_effort"]:
            raise ReplayError("runner model or reasoning effort differs from the paired settings")
        result["actions"] = parse_actions(raw)
        result["status"] = "ok"
    except Exception as exc:
        # Client exceptions can include request bodies/headers. Retain only a
        # bounded error category; full prompts already have a local audit record.
        result["error"] = type(exc).__name__
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    return result, raw


def paired_metrics(cases, *, horizon=3):
    """Same assessed, prospective, nonoverlapping cases on both sides; paper only."""
    from .opportunities import _dates

    prospective = [c for c in cases if c.get("eligible_for_recall") is True and c.get("coverage") == "prospective_screener"]
    # Reserve first episodes using decision-time dates alone. Action assessment,
    # missing outcomes or failed replays must not allow a later overlapping BUY
    # to replace an earlier missed/unassessed candidate in the denominator.
    episodes, last_exit, deduplicated = [], {}, 0
    for case in sorted(prospective, key=lambda c: (str(c.get("observed_at") or ""), int(c.get("id") or 0),
                                                   int(c.get("source_input_id") or c.get("input_id") or 0))):
        try:
            dates = _dates(case, horizon)
        except (TypeError, ValueError, KeyError):
            dates = None
        if not dates:
            episodes.append((case, None))
            continue
        ticker = case["ticker"]
        if ticker in last_exit and dates[0] <= last_exit[ticker]:
            deduplicated += 1
            continue
        last_exit[ticker] = dates[-1]
        episodes.append((case, dates))
    eligible, excluded = [], len(cases) - len(episodes)
    for case, dates in episodes:
        outcome = (case.get("outcomes") or {}).get(str(horizon)) or {}
        value = outcome.get("net_return_pct")
        side_cost = outcome.get("side_cost_bps")
        ready = (dates is not None
                 and case.get("incumbent_status") == "ok" and case.get("candidate_status") == "ok"
                 and case.get("incumbent_action") in ("BUY", "PASS") and case.get("candidate_action") in ("BUY", "PASS")
                 and outcome.get("status") == "matured" and isinstance(value, (float, int))
                 and not isinstance(value, bool) and math.isfinite(value)
                 and outcome.get("label") in ("winner", "loser", "break_even")
                 and outcome.get("horizon") == horizon
                 and isinstance(side_cost, (int, float)) and not isinstance(side_cost, bool)
                 and math.isfinite(side_cost) and 0 <= side_cost < 10000
                 and outcome.get("calendar_id") and outcome.get("execution")
                 and outcome.get("entry_date") == dates[0].isoformat()
                 and outcome.get("exit_date") == dates[-1].isoformat())
        if not ready:
            excluded += 1
            continue
        eligible.append((case, outcome))
    specs = {(o.get("spec_id"), o.get("horizon"), o.get("side_cost_bps"), o.get("calendar_id"), o.get("execution"))
             for _, o in eligible}
    if len(specs) > 1 or any(not s[0] for s in specs):
        # Returns with different horizons/costs/entry conventions are not one
        # target. Do not average them into a plausible-looking score.
        return {"comparable": 0, "excluded": len(cases), "horizon": horizon, "measurable": False,
                "note": "Paper outcome specifications differ or are unrecorded", "incumbent": None, "candidate": None}
    def side_stats(side):
        buys = [(case, outcome) for case, outcome in eligible if case[side + "_action"] == "BUY"]
        wins = sum(o.get("label") == "winner" for _, o in eligible)
        losses = sum(o.get("label") == "loser" for _, o in eligible)
        tp = sum(o.get("label") == "winner" for _, o in buys)
        fp = sum(o.get("label") == "loser" for _, o in buys)
        returns = [float(o["net_return_pct"]) for _, o in buys]
        return {"assessed": len(eligible), "buys": len(buys), "winners": wins, "losers": losses,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / wins if wins else None, "fpr": fp / losses if losses else None,
                "mean_net_return_pct": sum(returns) / len(returns) if returns else None,
                "paper_pnl_per_1000_tickets": sum(returns) * 10 if returns else 0.0,
                "participation": len(buys) / len(eligible) if eligible else None}
    incumbent, candidate = side_stats("incumbent"), side_stats("candidate")
    return {"comparable": len(eligible), "excluded": excluded, "horizon": horizon,
            "prospective_cases": len(prospective), "episodes": len(episodes), "deduplicated": deduplicated,
            "spec_id": next(iter(specs))[0] if specs else None,
            "measurable": len(eligible) >= MIN_COMPARABLE, "incumbent": incumbent, "candidate": candidate,
            "paper_pnl_delta_per_1000_tickets": candidate["paper_pnl_per_1000_tickets"] - incumbent["paper_pnl_per_1000_tickets"],
            "note": "Retrospective paired paper outcomes; equal $1,000 hypothetical tickets, no portfolio/exposure simulation or causal/forward-quality claim."
                    if len(eligible) >= MIN_COMPARABLE else "Insufficient comparable matured prospective cases; no quality conclusion."}


def run_comparison(engine, config_hash, *, source_input_ids, candidate_version, runner, expected_cohort_hash=None, **kwargs):
    """Explicit bounded execution. Persist the cohort BEFORE the first model call."""
    if not callable(runner):
        raise ReplayError("an explicit model runner is required")
    prepared = _prepare(engine, config_hash, source_input_ids, candidate_version, **kwargs)
    if expected_cohort_hash is not None and expected_cohort_hash != prepared["cohort_hash"]:
        raise ReplayError("saved inputs, policy or outcome snapshot changed since preview; preview again")
    ensure_schema(engine)
    frozen = prepared["frozen"]
    params = {"h": config_hash, "status": "running", "source": "paired_policy_replay",
              "iv": prepared["incumbent_version"], "cv": prepared["candidate_version"], "m": prepared["model"],
              "e": prepared["reasoning_effort"], "mode": prepared["assembly_mode"], "cohort": prepared["cohort_hash"],
              "frozen": _json(frozen), "summary": _json({"note": "Replay started; no orders or activation"})}
    with engine.begin() as conn:
        replay_id = int(conn.execute(text("""
            INSERT INTO policy_learning_replays (config_hash,status,source_kind,incumbent_version,candidate_version,
                model,reasoning_effort,assembly_mode,cohort_hash,frozen_json,summary_json)
            VALUES (:h,:status,:source,:iv,:cv,:m,:e,:mode,:cohort,:frozen,:summary) RETURNING id
        """), params).scalar_one())
    results, costs = {}, []
    for request in prepared["requests"]:
        result, raw = _call(runner, request)
        results[(request["source_input_id"], request["side"])] = result
        costs.append(result["cost_usd"])
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO policy_learning_replay_calls
                    (config_hash,replay_id,source_input_id,side,status,model,reasoning_effort,request_hash,
                     system_prompt,user_prompt,raw_reply,result_json)
                VALUES (:h,:r,:i,:side,:status,:model,:effort,:hash,:system,:user,:raw,:result)
            """), {"h": config_hash, "r": replay_id, "i": request["source_input_id"], "side": request["side"],
                   "status": result["status"], "model": request["model"], "effort": request["reasoning_effort"],
                   "hash": request["request_hash"], "system": request["system_prompt"], "user": request["user_prompt"],
                   "raw": raw if isinstance(raw, str) else _json(raw) if raw is not None else None, "result": _json(result)})
    actual_models = {r["actual_model"] for r in results.values() if r.get("status") == "ok"}
    if len(actual_models) > 1:
        # Even two valid dated resolutions are not a paired model comparison.
        # Keep billing/audit evidence, invalidate every quality denominator.
        for request in prepared["requests"]:
            result = results[(request["source_input_id"], request["side"])]
            result.update(status="error", error="ModelChangedWithinComparison", actions={})
            with engine.begin() as conn:
                conn.execute(text("""UPDATE policy_learning_replay_calls SET status='error',result_json=:j
                    WHERE config_hash=:h AND replay_id=:r AND source_input_id=:i AND side=:s"""),
                    {"j": _json(result), "h": config_hash, "r": replay_id, "i": request["source_input_id"], "s": request["side"]})
    observed = {}
    for source in prepared["sources"]:
        try:
            observed[source["id"]] = parse_actions(source.get("raw_reply"))
        except ReplayError:
            observed[source["id"]] = {}
    cases = []
    for case in frozen["cases"]:
        case = copy.deepcopy(case)
        input_id, ticker = int(case["input_id"]), case["ticker"]
        case["source_input_id"] = input_id
        case["observed_action"] = observed[input_id].get(ticker, {}).get("action", case.get("action") or "NOT_ASSESSED")
        for side in ("incumbent", "candidate"):
            result = results[(input_id, side)]
            action = result["actions"].get(ticker, {})
            case[side + "_status"] = result["status"]
            case[side + "_action"] = action.get("action", "NOT_ASSESSED")
            case[side + "_reason"] = action.get("reason", "")
            case[side + "_cited"] = action.get("cited", [])
        case["action_changed"] = (case["incumbent_action"] in ACTIONS and case["candidate_action"] in ACTIONS
                                  and case["incumbent_action"] != case["candidate_action"])
        cases.append(case)
    failures = sum(r["status"] != "ok" for r in results.values())
    known = [float(c) for c in costs if c is not None]
    summary = {"source_input_ids": frozen["source_input_ids"], "model_calls": len(results), "errors": failures,
               "case_count": len(cases), "action_flips": sum(c["action_changed"] for c in cases),
               "cost_usd": sum(known) if len(known) == len(costs) else None,
               "known_cost_usd": sum(known) if known else None, "unknown_cost_calls": len(costs) - len(known),
               "changed_ids": frozen["changed_ids"], "incumbent_policy_hash": frozen["incumbent_policy_hash"],
               "actual_model": next(iter(actual_models)) if len(actual_models) == 1 else None,
               "candidate_policy_hash": frozen["candidate_policy_hash"], "outcome_spec": frozen["outcome_spec"],
               "metrics": paired_metrics(cases, horizon=frozen["outcome_spec"]["horizon"]),
               "note": "Paired policy replay, not live trading. Original observed actions are separate from recomputed incumbent actions. No automatic activation."}
    status = "ok" if not failures else "partial" if failures < len(results) else "error"
    with engine.begin() as conn:
        for case in cases:
            conn.execute(text("""
                INSERT INTO policy_learning_replay_cases (config_hash,replay_id,source_input_id,ticker,case_json)
                VALUES (:h,:r,:i,:t,:case)
            """), {"h": config_hash, "r": replay_id, "i": case["source_input_id"], "t": case["ticker"], "case": _json(case)})
        conn.execute(text("UPDATE policy_learning_replays SET status=:s,summary_json=:j WHERE id=:r AND config_hash=:h"),
                     {"s": status, "j": _json(summary), "r": replay_id, "h": config_hash})
    return get_replay(engine, config_hash, replay_id)


def _public(row):
    out = {key: _iso(row[key]) for key in ("id", "created_at", "status", "source_kind", "incumbent_version",
                                          "candidate_version", "model", "reasoning_effort", "assembly_mode", "cohort_hash")}
    out.update(json.loads(row["summary_json"]))
    return out


def list_replays(engine, config_hash, *, limit=20):
    """Public bounded summaries. Reading an uninitialized database is harmless."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM policy_learning_replays WHERE config_hash=:h ORDER BY id DESC LIMIT :n"),
                                {"h": config_hash, "n": max(1, min(int(limit), 100))}).mappings().all()
        return [_public(row) for row in rows]
    except Exception:
        return []


def get_replay(engine, config_hash, replay_id):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM policy_learning_replays WHERE id=:r AND config_hash=:h"),
                           {"r": int(replay_id), "h": config_hash}).mappings().first()
        if not row:
            raise ReplayError("replay unavailable for this configuration")
        cases = conn.execute(text("SELECT case_json FROM policy_learning_replay_cases WHERE replay_id=:r AND config_hash=:h ORDER BY source_input_id,ticker"),
                             {"r": int(replay_id), "h": config_hash}).scalars().all()
    out = _public(row)
    out["cases"] = [json.loads(case) for case in cases]
    return out


def openai_runner(client, *, max_completion_tokens=3000, cost_fn=None, usage_callback=None):
    """Create an explicitly invoked Chat Completions runner from an injected client.

    Instantiate that client with ``max_retries=0`` and a bounded timeout. No
    tools, sampling changes, prompt rewriting, fallback or remote storage. The
    completion cap includes reasoning tokens; truncation is an error, not PASS.
    Reference: https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create
    """
    cap = int(max_completion_tokens)
    if not 128 <= cap <= 12000:
        raise ReplayError("completion token cap must be between 128 and 12000")
    def run(request):
        params = {"model": request["model"], "messages": [
            {"role": "system", "content": request["system_prompt"]},
            {"role": "user", "content": request["user_prompt"]}],
            "max_completion_tokens": cap, "store": False}
        if request["reasoning_effort"] is not None:
            params["reasoning_effort"] = request["reasoning_effort"]
        response = client.chat.completions.create(**params)
        usage_obj = getattr(response, "usage", None)
        usage = {key: int(getattr(usage_obj, key, 0) or 0)
                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")} if usage_obj else {}
        details = getattr(usage_obj, "prompt_tokens_details", None)
        if details is not None:
            usage["cached_input_tokens"] = int(getattr(details, "cached_tokens", 0) or 0)
        if usage_callback is not None:
            usage_callback(request, response)
        actual_model = getattr(response, "model", None)
        choices = getattr(response, "choices", None) or []
        reply = choices[0].message.content if choices else ""
        # Return incomplete text for strict parse failure while retaining usage.
        if choices and getattr(choices[0], "finish_reason", None) not in ("stop", None):
            reply = ""
        cost = cost_fn(actual_model, usage["prompt_tokens"], usage["completion_tokens"]) if cost_fn and usage else None
        return {"reply": reply, "model": actual_model, "reasoning_effort": request["reasoning_effort"],
                "usage": usage, "cost_usd": cost}
    return run


__all__ = ["ReplayError", "MODES", "DDL_POSTGRES", "DDL_SQLITE", "DDL_CALLS_POSTGRES", "DDL_CASES_POSTGRES",
           "ensure_schema", "preview_comparison", "run_comparison", "list_replays", "get_replay", "parse_actions", "paired_metrics", "openai_runner"]
