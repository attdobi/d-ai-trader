"""Phase 2 — the loop edits the graph.

A *proposal* is a patch of at most three guideline files against the active policy version of one
agent: `edit` (replace one guideline's text), `add` (a new guideline under an existing section) or
`remove`. Exactly one file is `primary` (the behavioral change); the others are minor supporting
edits. The flow is

    draft (LLM)  →  validate + dry-run round trip  →  critic (LLM, per file)  →  human review on
    the Policy Graph tab  →  apply: compile the approved files into the five prompt fields, insert
    the prompt_versions row, activate it through the injected `activate` switchboard, materialize
    the version directory.

Storage: proposals live in ONE SQL table (`policy_graph_proposals`, JSON as text so the same DDL
works on Postgres and SQLite). Guideline files are never stored in SQL — the version directory is
rebuilt from the compiled row by the store, exactly like every historical version, so the graph
stays a byte-exact mirror of `prompt_versions`.

Fidelity: a patch is applied on the node sequence of the base version (sep_before + body +
sep_after per node), compiled to text, and the text is decomposed again with the standard
builder. The proposal is accepted only when the decomposed bodies equal the patched bodies —
i.e. every edited/added guideline is still one file after the round trip.

This module never imports config, never reads os.environ, and never calls an LLM API itself:
`llm(role, system, user) -> str`, `context_fn(config_hash, agent_type) -> dict` and
`activate(conn, agent_type, config_hash, version, *, action, actor, reason)` are injected by the
dashboard (`policy_graph.routes.register_policy_graph_routes`).
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import traceback
from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import text

from . import service
from .compile import _field_meta, _inherited_ids, compile_effective, compile_stored
from .decompose import decompose_row, is_locked
from .model import AGENT_LABEL, AGENT_PREFIX, COMPILED_FIELDS, FIELDS, ID_RE, Node, RowMeta, Version
from .prompts import CRITIC_DOCTRINE, CRITIC_OUTPUT_FILES, DRAFTER_SYSTEM

MAX_FILES = 3
ACTIONS = ("edit", "add", "remove")
STATUSES = ("drafting", "critiquing", "review", "applied", "rejected", "failed")
IN_PROGRESS = ("drafting", "critiquing")
STALE_AFTER = timedelta(minutes=20)          # an in-progress row older than this lost its thread
CREATED_BY = "policy_graph"
MISSION_PHRASES = ("mission (shared across all agents", "shared principles (preserve verbatim")
BEHAVIORAL_RE = re.compile(
    r"\b(regime|kill|quarantine|extension|extended|harvest|never|must|only|cap|pass|half|full size|"
    r"risk-off|risk-on|20d|ma\b|stop|breach|re-?entry|slots?|position|size)\b", re.I)
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?%?")


class ProposalError(ValueError):
    """The proposal is malformed or does not apply (routes → 400)."""


class ProposalConflict(Exception):
    """Another proposal is in progress or the active version moved (routes → 409)."""


class NotConfigured(Exception):
    """No LLM / activation switchboard was injected (routes → 503)."""


# ----------------------------------------------------------------------------- data shapes
@dataclass
class FileChange:
    id: str
    action: str
    body: str = ""
    parent: Optional[str] = None
    title: str = ""
    primary: bool = False
    what: str = ""
    why: str = ""
    expected_effect: str = ""
    falsified_if: str = ""
    # derived
    field: str = ""
    kind: str = ""                 # major | minor
    proposed_id: str = ""          # what the drafter suggested (add)
    old_body: Optional[str] = None
    old_title: str = ""
    diff: list = dc_field(default_factory=list)
    diff_stats: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FileChange":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ----------------------------------------------------------------------------- schema
DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS policy_graph_proposals (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    config_hash VARCHAR(50) NOT NULL,
    agent_type TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    base_prompt_version_id INTEGER,
    status TEXT NOT NULL,
    created_by TEXT,
    focus TEXT,
    patch TEXT,
    critic TEXT,
    critic_at TIMESTAMP,
    human TEXT,
    human_at TIMESTAMP,
    review_id INTEGER,
    result_version INTEGER,
    result_prompt_version_id INTEGER,
    error TEXT,
    model TEXT
)
"""
DDL_SQLITE = DDL_POSTGRES.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")


def ensure_schema(engine) -> None:
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    ddl = DDL_POSTGRES if dialect == "postgresql" else DDL_SQLITE
    with engine.begin() as conn:
        conn.execute(text(ddl))


# ----------------------------------------------------------------------------- small helpers
def _now() -> datetime:
    return datetime.now()


def _loads(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _dumps(value) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def parse_llm_json(raw) -> dict:
    """Same tolerance as dashboard_server._parse_generated_prompt_payload (fenced / prefixed JSON)."""
    content = raw
    if isinstance(content, list):
        content = "\n".join(str(getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else p)) for p in content)
    content = (content or "").strip()
    if not content:
        raise ProposalError("the model returned an empty response")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            raise ProposalError("the model response was not valid JSON")
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ProposalError(f"the model response was not valid JSON ({exc})")
    if not isinstance(parsed, dict):
        raise ProposalError("the model response must be a JSON object")
    return parsed


def field_order(version: Version, field: str) -> list:
    """Node ids of one compiled field in document order (inherited fields use the default-file nodes)."""
    if _field_meta(version, field).get("inherited"):
        return _inherited_ids(version, field)
    return list((version.manifest.get("compile_order") or {}).get(field, []))


def _children(version: Version, parent_id: str, order: list) -> list:
    return [i for i in order if version.nodes.get(i) is not None and version.nodes[i].parent == parent_id]


def _subtree_end(order: list, parent_id: str) -> int:
    """Index in `order` of the last node of parent's subtree (parent itself when childless)."""
    last = order.index(parent_id)
    prefix = parent_id + "."
    for k, i in enumerate(order):
        if k > last and i.startswith(prefix):
            last = k
    return last


def _sibling_sep(version: Version, parent_id: str, order: list) -> str:
    kids = _children(version, parent_id, order)
    if len(kids) >= 2:
        a, b = version.nodes[kids[-2]], version.nodes[kids[-1]]
        return a.sep_after or b.sep_before or "\n"
    if len(kids) == 1:
        return "\n" if version.nodes[kids[0]].node_type == "rule" else "\n\n"
    return "\n\n"


def editable(node: Node) -> bool:
    return (node.owner in ("db", "default-file") and node.field in COMPILED_FIELDS
            and not node.locked and not is_locked(node.id, node.node_type))


# ----------------------------------------------------------------------------- kind (code-derived)
def derive_kind(change: FileChange) -> str:
    if change.action == "remove":
        return "major"
    if change.action == "add":
        if change.field == "memory" and ".log" in (change.parent or ""):
            return "minor"
        return "major"
    old = change.old_body or ""
    new = change.body or ""
    if " ".join(old.split()) == " ".join(new.split()):
        return "minor"
    if set(NUMBER_RE.findall(old)) != set(NUMBER_RE.findall(new)):
        return "major"
    old_words, new_words = old.split(), new.split()
    sm = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    changed_words = [w for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"
                     for w in old_words[i1:i2] + new_words[j1:j2]]
    if any(BEHAVIORAL_RE.search(w) for w in changed_words):     # only the words that actually changed
        return "major"
    return "minor"


# ----------------------------------------------------------------------------- validation
def normalize_files(raw_files, version: Version) -> list:
    """LLM/JSON → [FileChange] with structural checks against `version` (ids, locks, parents, count)."""
    if not isinstance(raw_files, list) or not raw_files:
        raise ProposalError("\"files\" must be a non-empty list")
    if len(raw_files) > MAX_FILES:
        raise ProposalError(f"at most {MAX_FILES} guideline files per proposal (got {len(raw_files)})")
    out = []
    seen = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ProposalError("each file must be an object")
        action = str(raw.get("action") or "").strip().lower()
        if action not in ACTIONS:
            raise ProposalError(f"action must be one of {', '.join(ACTIONS)} (got {action!r})")
        node_id = str(raw.get("id") or "").strip()
        body = raw.get("body")
        body = "" if body is None else str(body).replace("\r\n", "\n").replace("\r", "\n")
        body = re.sub(r"^(?:\s*<!--\s*[^>]*?\.md\s*-->\s*\n)+", "", body)     # drafters echo bundle markers
        body = body.strip("\n").rstrip()          # trailing whitespace would land in the separator, never the body
        ch = FileChange(
            id=node_id, action=action, body=body, parent=(str(raw.get("parent")).strip() if raw.get("parent") else None),
            title=str(raw.get("title") or "").strip(), primary=bool(raw.get("primary")),
            what=str(raw.get("what") or "").strip(), why=str(raw.get("why") or "").strip(),
            expected_effect=str(raw.get("expected_effect") or "").strip(),
            falsified_if=str(raw.get("falsified_if") or "").strip(),
        )
        if action in ("edit", "remove"):
            node = version.nodes.get(node_id)
            if node is None:
                raise ProposalError(f"{node_id or '(missing id)'} is not a guideline of v{version.version}")
            if not editable(node):
                raise ProposalError(f"{node_id} is locked or not an editable guideline (only strategy directives, "
                                    f"soul and memory guidelines can change)")
            ch.field = node.field
            ch.old_body = node.body
            ch.old_title = node.title
            if action == "edit":
                if not body.strip():
                    raise ProposalError(f"{node_id}: an edit needs the complete new text in \"body\"")
                if body == node.body:
                    raise ProposalError(f"{node_id}: the edit leaves the text unchanged")
            else:
                order = field_order(version, node.field)
                if any(i != node_id and i.startswith(node_id + ".") for i in order):
                    raise ProposalError(f"{node_id} has guidelines under it — remove those first")
        else:
            parent = version.nodes.get(ch.parent or "")
            if parent is None:
                raise ProposalError(f"add: parent {ch.parent or '(missing)'} is not a guideline of v{version.version}")
            if parent.field not in COMPILED_FIELDS or parent.owner not in ("db", "default-file"):
                raise ProposalError(f"add: cannot add under {parent.id} (only strategy directives, soul and memory)")
            if parent.node_type not in ("field", "section", "identity", "note", "reminder"):
                raise ProposalError(f"add: {parent.id} is a {parent.node_type}, not a section — new guidelines go "
                                    f"under a section")
            if not body.strip():
                raise ProposalError("add: \"body\" is required")
            ch.field = parent.field
            ch.proposed_id = node_id
            ch.old_body = None
            if not ch.title:
                ch.title = body.strip().splitlines()[0][:60]
        key = ch.id if action != "add" else f"add:{ch.parent}:{ch.body[:40]}"
        if key in seen:
            raise ProposalError(f"{ch.id or ch.parent}: listed twice")
        seen.add(key)
        out.append(ch)
    primaries = [c for c in out if c.primary]
    if len(primaries) != 1:
        raise ProposalError(f"exactly one file must be primary (got {len(primaries)})")
    if not primaries[0].falsified_if:
        raise ProposalError("the primary file needs \"falsified_if\" (which number over how many trades proves it wrong)")
    return out


# ----------------------------------------------------------------------------- patch application
def apply_patch(version: Version, files: list) -> tuple:
    """(new_fields, expected_bodies_by_field). `new_fields` is the stored view: untouched fields keep
    their stored value (None/'' stays as is); a touched inherited field becomes stored text."""
    stored = compile_stored(version)
    new_fields = dict(stored)
    expected: dict = {}
    touched = sorted({c.field for c in files})
    for f in touched:
        order = field_order(version, f)
        seq = []      # [id, sep_before, body, sep_after]
        for i in order:
            n = version.nodes[i]
            seq.append([i, n.sep_before, n.body, n.sep_after])
        index = {row[0]: row for row in seq}
        for ch in [c for c in files if c.field == f and c.action == "edit"]:
            index[ch.id][2] = ch.body
        for ch in [c for c in files if c.field == f and c.action == "remove"]:
            k = next(k for k, row in enumerate(seq) if row[0] == ch.id)
            removed = seq.pop(k)
            if k > 0:
                prev = seq[k - 1]
                if k >= len(seq):                      # it was the last node
                    prev[3] = removed[3]
                elif prev[3] == "":
                    prev[3] = removed[1] or removed[3] or "\n\n"
        for ch in [c for c in files if c.field == f and c.action == "add"]:
            ids = [row[0] for row in seq]
            if ch.parent not in ids:
                raise ProposalError(f"add: parent {ch.parent} is not in the {f} text")
            end = _subtree_end(ids, ch.parent)
            prev = seq[end]
            new_row = [f"__add__{len(seq)}", "", ch.body, prev[3]]     # the new item takes the old tail
            prev[3] = _sibling_sep(version, ch.parent, ids)               # ... and sits after a sibling separator
            seq.insert(end + 1, new_row)
        new_fields[f] = "".join(row[1] + row[2] + row[3] for row in seq)
        expected[f] = [row[2] for row in seq]
    return new_fields, expected


def _bodies_by_field(build) -> dict:
    out: dict = {}
    for n in build.nodes:
        if n.owner == "db" and n.field in COMPILED_FIELDS:
            out.setdefault(n.field, []).append((n.id, n.body, n.title))
    return out


def verify_patch(agent_type: str, config_hash: str, version: Version, files: list, new_fields: dict,
                 expected: dict, *, is_margin_account: bool) -> dict:
    """Dry-run: decompose the patched text with the standard builder and require the same bodies.
    Returns {file index → resolved node id} for edits/adds."""
    meta = RowMeta(prompt_version_id=0, created_at=_now(), created_by=CREATED_BY,
                   description="dry run", is_active=False)
    build = decompose_row(agent_type, config_hash, version.version + 1, new_fields, meta=meta, inherited={},
                          code_nodes=[], ltm_nodes=[], is_margin_account=is_margin_account)
    got = _bodies_by_field(build)
    resolved: dict = {}
    for f, want in expected.items():
        have = [b for _i, b, _t in got.get(f, [])]
        if sorted(have) != sorted(want):
            extra = [b for b in have if b not in want]
            missing = [b for b in want if b not in have]
            hint = ""
            if missing and extra:
                m = missing[0]
                merged = [b for b in extra if m in b]
                split = [b for b in extra if b in m]
                if merged:
                    hint = (f" — the new text of a guideline merged into its neighbour (it is not recognised as its "
                            f"own item; match the sibling format exactly, e.g. \"N. LABEL — text\" or \"- **#tag** text\")")
                elif split:
                    hint = " — one guideline's text splits into several (remove the \"## \" heading or blank-line-separated items inside it)"
            snippet = (missing or extra or [""])[0][:80]
            raise ProposalError(f"the {f} text does not round-trip one guideline per file{hint}; first difference: "
                                f"{snippet!r}")
        by_body = {}
        for i, b, t in got.get(f, []):
            by_body.setdefault(b, []).append((i, t))
        for k, ch in enumerate(files):
            if ch.field != f or ch.action == "remove":
                continue
            hits = by_body.get(ch.body) or []
            if hits:
                resolved[k] = hits[0]
    return resolved


def enrich(files: list, resolved: dict, base_version: int) -> None:
    """Fill diffs, kinds and resolved ids in place."""
    for k, ch in enumerate(files):
        if k in resolved:
            rid, title = resolved[k]
            if ch.action == "add":
                ch.id = rid
                ch.title = ch.title or title
            elif ch.action == "edit" and rid != ch.id:
                ch.proposed_id = ch.id       # the edit renames the guideline (title line changed)
                ch.id = rid
        a = (ch.old_body or "").splitlines()
        b = (ch.body or "").splitlines() if ch.action != "remove" else []
        ch.diff = list(difflib.unified_diff(a, b, fromfile=f"v{base_version}/{ch.proposed_id or ch.id}",
                                            tofile=f"proposal/{ch.id}" if ch.action != "remove" else "/dev/null",
                                            lineterm=""))
        ch.diff_stats = {"added": sum(1 for l in ch.diff if l.startswith("+") and not l.startswith("+++")),
                         "removed": sum(1 for l in ch.diff if l.startswith("-") and not l.startswith("---"))}
        ch.kind = derive_kind(ch)


def check_guards(version: Version, new_fields: dict) -> None:
    """The verbatim Mission / Shared Principles must survive when the base had them."""
    before = compile_effective(version)
    soul_before = (before.get("soul") or "").lower()
    if not all(p in soul_before for p in MISSION_PHRASES):
        return
    soul_after = new_fields.get("soul")
    if soul_after is None or soul_after == "":
        soul_after = before.get("soul") or ""
    if not all(p in soul_after.lower() for p in MISSION_PHRASES):
        raise ProposalError("the soul must keep the verbatim Mission and Shared Principles sections")


def prepare(agent_type: str, config_hash: str, version: Version, raw_files, *, is_margin_account: bool) -> tuple:
    """normalize → apply → verify → enrich → guards. Returns (files, new_fields)."""
    files = normalize_files(raw_files, version)
    new_fields, expected = apply_patch(version, files)
    resolved = verify_patch(agent_type, config_hash, version, files, new_fields, expected,
                            is_margin_account=is_margin_account)
    enrich(files, resolved, version.version)
    check_guards(version, new_fields)
    return files, new_fields


# ----------------------------------------------------------------------------- DB rows
_COLS = ("id", "created_at", "updated_at", "config_hash", "agent_type", "base_version", "base_prompt_version_id",
         "status", "created_by", "focus", "patch", "critic", "critic_at", "human", "human_at", "review_id",
         "result_version", "result_prompt_version_id", "error", "model")


def _row_dict(r) -> dict:
    m = dict(r._mapping)
    for k in ("patch", "critic", "human"):
        m[k] = _loads(m.get(k))
    for k in ("created_at", "updated_at", "critic_at", "human_at"):
        m[k] = service.health.to_datetime(m.get(k))
    return m


def _select(engine, where: str, params: dict, *, limit: Optional[int] = None) -> list:
    sql = f"SELECT {', '.join(_COLS)} FROM policy_graph_proposals WHERE {where} ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [_row_dict(r) for r in rows]


def load(engine, proposal_id: int) -> dict:
    rows = _select(engine, "id = :id", {"id": int(proposal_id)})
    if not rows:
        raise service.NotFound(f"proposal #{proposal_id} not found")
    return rows[0]


def _update(engine, proposal_id: int, **cols) -> None:
    cols["updated_at"] = _now()
    for k in ("patch", "critic", "human"):
        if k in cols:
            cols[k] = _dumps(cols[k])
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE policy_graph_proposals SET {sets} WHERE id = :id"), {**cols, "id": int(proposal_id)})


def _insert(engine, **cols) -> int:
    cols.setdefault("created_at", _now())
    cols["updated_at"] = cols["created_at"]
    for k in ("patch", "critic", "human"):
        if k in cols:
            cols[k] = _dumps(cols[k])
    keys = list(cols)
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    with engine.begin() as conn:
        sql = f"INSERT INTO policy_graph_proposals ({', '.join(keys)}) VALUES ({', '.join(':' + k for k in keys)})"
        if dialect == "postgresql":
            row = conn.execute(text(sql + " RETURNING id"), cols).fetchone()
            return int(row[0])
        res = conn.execute(text(sql), cols)
        return int(res.lastrowid)


def _expire_stale(engine, config_hash: str, agent_type: str) -> None:
    cutoff = _now() - STALE_AFTER
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE policy_graph_proposals
            SET status = 'failed', error = 'the dashboard restarted while this proposal was being drafted',
                updated_at = :now
            WHERE config_hash = :h AND agent_type = :a AND status IN ('drafting', 'critiquing') AND updated_at < :cutoff
        """), {"h": config_hash, "a": agent_type, "now": _now(), "cutoff": cutoff})


# ----------------------------------------------------------------------------- read side
def _ctx(engine, config_hash, repo_root, is_margin_account) -> service._Ctx:
    return service._Ctx(engine, config_hash, repo_root, is_margin_account)


def _read(ctx: service._Ctx, agent_type: str, version: int) -> Version:
    v, _action, _busy = service._ensure_and_read(ctx, agent_type, version, materialized_by=CREATED_BY)
    return v


def _applies_to(ctx: service._Ctx, agent_type: str, row: dict) -> dict:
    """Where an in-review proposal would land: the active version, provided every guideline it touches is
    unchanged since the base version (reminder-only weekly drift is fine)."""
    active = ctx.current_version(agent_type)
    base = int(row["base_version"])
    if active is None:
        return {"target_version": None, "ok": False, "reason": "no active version"}
    if active == base:
        return {"target_version": active, "ok": True, "reason": None}
    files = [FileChange.from_dict(f) for f in ((row.get("patch") or {}).get("files") or [])]
    try:
        bv = _read(ctx, agent_type, base)
        av = _read(ctx, agent_type, active)
    except Exception as exc:     # noqa: BLE001
        return {"target_version": active, "ok": False, "reason": f"could not read v{base}/v{active}: {exc}"}
    for ch in files:
        if ch.action == "add":
            if ch.parent not in av.nodes:
                return {"target_version": active, "ok": False,
                        "reason": f"v{active} no longer has {ch.parent}; draft again"}
            continue
        key = ch.proposed_id or ch.id
        b, a = bv.nodes.get(key), av.nodes.get(key)
        if a is None or b is None or a.body != b.body:
            return {"target_version": active, "ok": False,
                    "reason": f"v{active} changed {key} since v{base}; draft again against v{active}"}
    return {"target_version": active, "ok": True,
            "reason": f"rebased onto v{active} (the guidelines it edits are unchanged since v{base})"}


def _public(row: dict, applies: Optional[dict] = None) -> dict:
    patch = row.get("patch") or {}
    files = patch.get("files") or []
    critic = row.get("critic") or {}
    per_file = {f.get("id"): f for f in (critic.get("files") or []) if isinstance(f, dict)}
    out = {
        "id": row["id"], "status": row["status"], "agent_type": row["agent_type"],
        "created_at": service._iso(row.get("created_at")), "updated_at": service._iso(row.get("updated_at")),
        "created_by": row.get("created_by"), "focus": row.get("focus"), "model": row.get("model"),
        "base_version": row["base_version"], "base_prompt_version_id": row.get("base_prompt_version_id"),
        "reasoning": patch.get("reasoning") or "",
        "files": [{**f, "critic": per_file.get(f.get("id"))} for f in files],
        "primary_id": next((f.get("id") for f in files if f.get("primary")), None),
        "critic": {k: v for k, v in critic.items() if k != "files"} if critic else None,
        "critic_at": service._iso(row.get("critic_at")),
        "human": row.get("human"), "human_at": service._iso(row.get("human_at")),
        "review_id": row.get("review_id"), "result_version": row.get("result_version"),
        "result_prompt_version_id": row.get("result_prompt_version_id"),
        "error": row.get("error"),
        "applies_to": applies,
    }
    return service._json_safe(out)


def list_proposals(engine, config_hash: str, agent_type: str, *, repo_root, is_margin_account: bool,
                   limit: int = 20) -> dict:
    service._check_agent(agent_type)
    ensure_schema(engine)
    _expire_stale(engine, config_hash, agent_type)
    rows = _select(engine, "config_hash = :h AND agent_type = :a", {"h": config_hash, "a": agent_type}, limit=limit)
    ctx = _ctx(engine, config_hash, repo_root, is_margin_account)
    items = []
    for r in rows:
        applies = _applies_to(ctx, agent_type, r) if r["status"] == "review" else None
        items.append(_public(r, applies))
    return {"agent_type": agent_type, "config_hash": config_hash, "active_version": ctx.current_version(agent_type),
            "in_progress": any(r["status"] in IN_PROGRESS for r in rows), "proposals": items}


def get_proposal(engine, proposal_id: int, *, repo_root, is_margin_account: bool) -> dict:
    ensure_schema(engine)
    row = load(engine, proposal_id)
    ctx = _ctx(engine, row["config_hash"], repo_root, is_margin_account)
    applies = _applies_to(ctx, row["agent_type"], row) if row["status"] == "review" else None
    return _public(row, applies)


# ----------------------------------------------------------------------------- drafter input
def _guideline_view(version: Version) -> tuple:
    guidelines, locked = [], []
    for f in COMPILED_FIELDS:
        for i in field_order(version, f):
            n = version.nodes.get(i)
            if n is None:
                continue
            item = {"id": n.id, "title": n.title, "node_type": n.node_type, "field": f, "parent": n.parent,
                    "locked": not editable(n), "body": n.body}
            if item["locked"]:
                locked.append(n.id)
            guidelines.append(item)
    return guidelines, locked


def _read_only_context(version: Version) -> dict:
    code = [{"id": n.id, "title": n.title, "body": n.body} for n in version.nodes.values()
            if n.owner == "code" and n.node_type == "code" and n.extra.get("fires", True) and (n.body or "").strip()]
    ltm = [{"id": n.id, "body": n.body} for n in version.nodes.values()
           if n.owner == "decider_memory" and n.node_type == "ltm" and n.parent and n.extra.get("injected")]
    templates = {}
    for f in ("system_prompt", "user_prompt_template"):
        ids = (version.manifest.get("compile_order") or {}).get(f) or []
        templates[f] = version.nodes[ids[0]].body if ids and ids[0] in version.nodes else ""
    return {"code_owned_blocks_appended_at_runtime": code, "long_term_memory_rows_injected": ltm,
            "templates_read_only": templates}


def _past_proposals(engine, config_hash: str, agent_type: str, limit: int = 8) -> list:
    rows = _select(engine, "config_hash = :h AND agent_type = :a AND status IN ('applied', 'rejected', 'review')",
                   {"h": config_hash, "a": agent_type}, limit=limit)
    out = []
    for r in rows:
        files = ((r.get("patch") or {}).get("files") or [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else {})
        out.append({"id": r["id"], "status": r["status"], "created_at": service._iso(r.get("created_at")),
                    "base_version": r["base_version"], "result_version": r.get("result_version"),
                    "primary": {k: primary.get(k) for k in ("id", "action", "what", "why")},
                    "critic_verdict": (r.get("critic") or {}).get("verdict"),
                    "critic_reason": (r.get("critic") or {}).get("reason"),
                    "human_verdict": (r.get("human") or {}).get("verdict")})
    return out


def draft_input(engine, ctx: service._Ctx, agent_type: str, version: Version, *, focus: str,
                context: dict) -> dict:
    guidelines, locked = _guideline_view(version)
    payload = {
        "agent_type": agent_type, "agent_label": AGENT_LABEL[agent_type], "base_version": version.version,
        "editable_guidelines": guidelines, "locked_ids": locked,
        "read_only_context": _read_only_context(version),
        "past_proposals": _past_proposals(engine, ctx.config_hash, agent_type),
    }
    payload.update(context or {})
    if focus:
        payload["human_focus"] = focus
    return payload


def critic_input(agent_type: str, version: Version, files: list, reasoning: str, context: dict) -> dict:
    payload = {
        "agent_type": agent_type, "base_version": version.version, "reasoning": reasoning,
        "files": [{"id": c.id, "action": c.action, "field": c.field, "title": c.title or c.old_title,
                   "kind": c.kind, "primary": c.primary, "what": c.what, "why": c.why,
                   "expected_effect": c.expected_effect, "falsified_if": c.falsified_if,
                   "diff": c.diff, "new_body": (c.body if c.action != "remove" else None)} for c in files],
        "change_summary": summarize(files),
    }
    payload.update(context or {})
    return payload


def summarize(files: list) -> dict:
    major = sum(1 for c in files if c.kind == "major")
    return {"total": len(files), "major": major, "minor": len(files) - major, "behavioral": major,
            "is_substantive": major > 0}


def changes_for_review(files: list) -> list:
    """The Prompt Lab `changes` shape so the critic scorecard and history keep working."""
    return [{"section": c.field, "kind": c.kind, "behavioral": c.kind == "major", "what": c.what, "why": c.why,
             "expected_effect": c.expected_effect, "falsified_if": c.falsified_if, "node_id": c.id,
             "action": c.action, "primary": c.primary} for c in files]


# ----------------------------------------------------------------------------- pipeline
def _dumps_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def run_critic(llm, agent_type: str, version: Version, files: list, reasoning: str, context: dict) -> dict:
    summary = summarize(files)
    if not summary["is_substantive"]:
        return {"verdict": "reject", "confidence": 0.9, "auto": True,
                "reason": "Cosmetic only — no behavioral change. Rewording does not move win rate.",
                "ship_first": None, "unexecutable_gates": [],
                "files": [{"id": c.id, "verdict": "reject", "reason": "wording only"} for c in files]}
    try:
        raw = llm("critic", CRITIC_DOCTRINE + CRITIC_OUTPUT_FILES,
                  "Review this proposed patch of guideline files:\n\n" + _dumps_payload(critic_input(agent_type, version, files, reasoning, context)))
        parsed = parse_llm_json(raw)
    except Exception as exc:     # noqa: BLE001 — never block the human on a critic outage
        return {"verdict": "reject", "confidence": 0.0, "auto": False,
                "reason": f"Critic unavailable ({exc}); defer to human review.", "ship_first": None,
                "unexecutable_gates": [], "files": []}
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict not in ("approve", "reject"):
        verdict = "reject"
    try:
        conf = max(0.0, min(1.0, float(parsed.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.5
    reason = str(parsed.get("reason") or "").strip() or "No reason returned."
    ship_first = parsed.get("ship_first") or None
    gates = [str(g) for g in (parsed.get("unexecutable_gates") or []) if g][:4]
    per_file = []
    known = {c.id for c in files}
    for f in parsed.get("files") or []:
        if not isinstance(f, dict) or f.get("id") not in known:
            continue
        v = str(f.get("verdict") or "").strip().lower()
        per_file.append({"id": f["id"], "verdict": v if v in ("approve", "reject") else "reject",
                         "reason": str(f.get("reason") or "").strip()})
    for c in files:
        if c.id not in {f["id"] for f in per_file}:
            per_file.append({"id": c.id, "verdict": verdict, "reason": "(no per-file verdict returned)"})
    return {"verdict": verdict, "confidence": conf, "auto": False, "reason": reason, "ship_first": ship_first,
            "unexecutable_gates": gates, "files": per_file}


def _record_review(engine, config_hash: str, agent_type: str, base_version: int, files: list, critic: dict) -> Optional[int]:
    summary = summarize(files)
    reason = critic.get("reason") or ""
    if critic.get("ship_first"):
        reason += f" Ship first: {critic['ship_first']}."
    if critic.get("unexecutable_gates"):
        reason += " Unexecutable gates: " + "; ".join(critic["unexecutable_gates"]) + "."
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    cast = "CAST(:v AS JSONB)" if dialect == "postgresql" else ":v"
    try:
        with engine.begin() as conn:
            sql = f"""
                INSERT INTO prompt_change_reviews (config_hash, agent_type, from_version, change_summary, changes,
                    is_substantive, critic_verdict, critic_reason, critic_confidence, critic_at, critic_auto)
                VALUES (:h, :a, :f, {cast.replace(':v', ':summary')}, {cast.replace(':v', ':changes')}, :subst, :cv, :cr, :conf, :at, :auto)
            """
            params = {"h": config_hash, "a": agent_type, "f": base_version, "summary": json.dumps(summary),
                      "changes": json.dumps(changes_for_review(files)), "subst": bool(summary["is_substantive"]),
                      "cv": critic.get("verdict"), "cr": reason, "conf": critic.get("confidence"), "at": _now(),
                      "auto": bool(critic.get("auto"))}
            if dialect == "postgresql":
                row = conn.execute(text(sql + " RETURNING id"), params).fetchone()
                return int(row[0])
            res = conn.execute(text(sql), params)
            return int(res.lastrowid)
    except Exception as exc:     # noqa: BLE001 — recording never blocks the flow
        print(f"⚠️  policy graph: could not record the critic review: {exc}")
        return None


def run_pipeline(engine, proposal_id: int, *, repo_root, is_margin_account: bool, llm, context_fn,
                 model: Optional[str] = None) -> dict:
    """Draft → validate (one retry) → critic → review. Returns the final row. Never raises."""
    row = load(engine, proposal_id)
    config_hash, agent_type, base = row["config_hash"], row["agent_type"], int(row["base_version"])
    try:
        ctx = _ctx(engine, config_hash, repo_root, is_margin_account)
        version = _read(ctx, agent_type, base)
        context = {}
        if context_fn is not None:
            try:
                context = context_fn(config_hash, agent_type) or {}
            except Exception as exc:     # noqa: BLE001
                context = {"context_error": f"{type(exc).__name__}: {exc}"}
        user = "Draft a proposal from this input:\n\n" + _dumps_payload(
            draft_input(engine, ctx, agent_type, version, focus=row.get("focus") or "", context=context))
        files, reasoning, last_error = None, "", None
        for attempt in range(2):
            prompt = user if last_error is None else (
                user + "\n\nYOUR PREVIOUS OUTPUT WAS REJECTED BY THE VALIDATOR: " + last_error +
                "\nFix exactly that and return the full JSON again.")
            raw = llm("drafter", DRAFTER_SYSTEM, prompt)
            try:
                parsed = parse_llm_json(raw)
                reasoning = str(parsed.get("reasoning") or "").strip()
                files, _new_fields = prepare(agent_type, config_hash, version, parsed.get("files"),
                                             is_margin_account=is_margin_account)
                break
            except ProposalError as exc:
                last_error = str(exc)
                files = None
        if files is None:
            _update(engine, proposal_id, status="failed", error=f"the drafter's patch did not validate: {last_error}")
            return load(engine, proposal_id)
        patch = {"reasoning": reasoning, "files": [c.to_dict() for c in files]}
        _update(engine, proposal_id, status="critiquing", patch=patch, model=model)
        critic = run_critic(llm, agent_type, version, files, reasoning, context)
        review_id = _record_review(engine, config_hash, agent_type, base, files, critic)
        _update(engine, proposal_id, status="review", critic=critic, critic_at=_now(), review_id=review_id)
    except Exception as exc:     # noqa: BLE001
        traceback.print_exc()
        _update(engine, proposal_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    return load(engine, proposal_id)


def start_draft(engine, config_hash: str, agent_type: str, *, repo_root, is_margin_account: bool, llm, context_fn,
                focus: str = "", created_by: str = "dashboard", model: Optional[str] = None,
                background: bool = True) -> dict:
    """Insert the proposal row and run the pipeline (in a daemon thread by default)."""
    service._check_agent(agent_type)
    if llm is None:
        raise NotConfigured("proposal drafting is not configured on this dashboard (no model client)")
    ensure_schema(engine)
    _expire_stale(engine, config_hash, agent_type)
    ctx = _ctx(engine, config_hash, repo_root, is_margin_account)
    active = ctx.current_version(agent_type)
    if active is None:
        raise service.NotFound(f"{agent_type} has no active policy version for config {config_hash}")
    busy = _select(engine, "config_hash = :h AND agent_type = :a AND status IN ('drafting', 'critiquing')",
                   {"h": config_hash, "a": agent_type}, limit=1)
    if busy:
        raise ProposalConflict(f"proposal #{busy[0]['id']} is still being drafted for {AGENT_LABEL[agent_type]}")
    row = ctx.row(agent_type, active)
    pid = _insert(engine, config_hash=config_hash, agent_type=agent_type, base_version=active,
                  base_prompt_version_id=row["id"], status="drafting", created_by=created_by,
                  focus=(focus or "").strip()[:2000] or None, model=model)
    kwargs = dict(repo_root=repo_root, is_margin_account=is_margin_account, llm=llm, context_fn=context_fn, model=model)
    if background:
        t = threading.Thread(target=run_pipeline, args=(engine, pid), kwargs=kwargs, daemon=True,
                             name=f"policy-proposal-{pid}")
        t.start()
        return {"id": pid, "status": "drafting", "base_version": active}
    run_pipeline(engine, pid, **kwargs)
    return get_proposal(engine, pid, repo_root=repo_root, is_margin_account=is_margin_account)


# ----------------------------------------------------------------------------- human decisions
def _review_update(engine, review_id: Optional[int], *, verdict: str, to_version: Optional[int], sections: dict) -> None:
    if not review_id:
        return
    dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
    sections_sql = "CAST(:sections AS JSONB)" if dialect == "postgresql" else ":sections"
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                UPDATE prompt_change_reviews
                SET human_verdict = :verdict, human_at = :now,
                    to_version = COALESCE(:to_version, to_version),
                    human_sections = {sections_sql},
                    human_agrees_critic = CASE
                        WHEN :verdict = 'partial' THEN NULL
                        WHEN COALESCE(critic_auto, FALSE) OR COALESCE(critic_confidence, 0) = 0 THEN NULL
                        ELSE (critic_verdict = :verdict) END
                WHERE id = :id
            """), {"verdict": verdict, "now": _now(), "to_version": to_version,
                   "sections": json.dumps(sections), "id": int(review_id)})
    except Exception as exc:     # noqa: BLE001
        print(f"⚠️  policy graph: could not record the human decision on review #{review_id}: {exc}")


def reject_proposal(engine, proposal_id: int, *, reason: str = "", actor: str = "dashboard") -> dict:
    ensure_schema(engine)
    row = load(engine, proposal_id)
    if row["status"] not in ("review", "failed"):
        raise ProposalConflict(f"proposal #{proposal_id} is {row['status']} — only proposals awaiting review can be rejected")
    human = {"verdict": "reject", "reason": (reason or "").strip()[:1000], "actor": actor, "approved": [],
             "rejected": [f.get("id") for f in ((row.get("patch") or {}).get("files") or [])]}
    _update(engine, proposal_id, status="rejected", human=human, human_at=_now())
    _review_update(engine, row.get("review_id"), verdict="reject", to_version=None,
                   sections={"approved": [], "rejected": human["rejected"]})
    return _public(load(engine, proposal_id))


def apply_proposal(engine, proposal_id: int, approved_ids: list, *, repo_root, is_margin_account: bool, activate,
                   actor: str = "dashboard") -> dict:
    """Mint the next version from the approved files, activate it, materialize its directory."""
    ensure_schema(engine)
    if activate is None:
        raise NotConfigured("applying proposals is not configured on this dashboard (no activation switchboard)")
    row = load(engine, proposal_id)
    if row["status"] != "review":
        raise ProposalConflict(f"proposal #{proposal_id} is {row['status']} — only proposals awaiting review can be applied")
    config_hash, agent_type = row["config_hash"], row["agent_type"]
    all_files = [FileChange.from_dict(f) for f in ((row.get("patch") or {}).get("files") or [])]
    if not all_files:
        raise ProposalError("the proposal has no files")
    approved = {str(i) for i in (approved_ids or [])}
    primary = next((c for c in all_files if c.primary), None)
    if primary is None or primary.id not in approved:
        raise ProposalError("the primary guideline must be included — reject the proposal instead")
    chosen = [c for c in all_files if c.id in approved]
    unknown = approved - {c.id for c in all_files}
    if unknown:
        raise ProposalError(f"unknown guideline ids: {', '.join(sorted(unknown))}")

    ctx = _ctx(engine, config_hash, repo_root, is_margin_account)
    applies = _applies_to(ctx, agent_type, row)
    if not applies["ok"]:
        raise ProposalConflict(applies["reason"] or "the proposal no longer applies")
    target_n = int(applies["target_version"])
    target = _read(ctx, agent_type, target_n)
    target_row = ctx.row(agent_type, target_n)

    # re-run the patch on the target (rebase-safe: touched guidelines are unchanged since the base)
    raw = []
    for c in chosen:
        d = {"id": (c.proposed_id or c.id) if c.action != "add" else c.id, "action": c.action, "body": c.body,
             "parent": c.parent, "title": c.title, "primary": c.primary, "what": c.what, "why": c.why,
             "expected_effect": c.expected_effect, "falsified_if": c.falsified_if}
        raw.append(d)
    files, new_fields = prepare(agent_type, config_hash, target, raw, is_margin_account=is_margin_account)

    label = AGENT_LABEL[agent_type]
    what = (primary.what or primary.title or primary.id)[:140]
    description = (f"v{{n}} {label} (policy graph proposal #{proposal_id}) · {primary.action} {primary.id}: {what}"
                   f" · {len(files)} of {len(all_files)} guideline files approved")
    sections = {"approved": [c.id for c in files], "rejected": [c.id for c in all_files if c.id not in approved]}
    verdict = "approve" if not sections["rejected"] else "partial"

    with engine.begin() as conn:
        max_row = conn.execute(text("""
            SELECT COALESCE(MAX(version), -1) AS max_version FROM prompt_versions
            WHERE agent_type = :a AND config_hash = :h
        """), {"a": agent_type, "h": config_hash}).fetchone()
        new_version = int(max_row[0]) + 1
        description = description.replace("{n}", str(new_version))
        params = {"a": agent_type, "v": new_version, "h": config_hash, "d": description, "by": CREATED_BY,
                  **{f: new_fields.get(f) for f in FIELDS}}
        for f in ("system_prompt", "user_prompt_template"):
            if params[f] is None:
                params[f] = target_row.get(f)
        dialect = getattr(getattr(engine, "dialect", None), "name", "") or ""
        sql = """
            INSERT INTO prompt_versions (agent_type, version, system_prompt, user_prompt_template, strategy_directives,
                soul, memory, description, created_by, is_active, config_hash)
            VALUES (:a, :v, :system_prompt, :user_prompt_template, :strategy_directives, :soul, :memory, :d, :by,
                FALSE, :h)
        """
        if dialect == "postgresql":
            new_id = int(conn.execute(text(sql + " RETURNING id"), params).fetchone()[0])
        else:
            new_id = int(conn.execute(text(sql.replace("FALSE", "0")), params).lastrowid)
        change = activate(conn, agent_type, config_hash, new_version, action="apply_proposal", actor=actor,
                          reason=description)
        human = {"verdict": verdict, "actor": actor, **sections, "applied_on": target_n}
        conn.execute(text("""
            UPDATE policy_graph_proposals
            SET status = 'applied', human = :human, human_at = :now, updated_at = :now,
                result_version = :rv, result_prompt_version_id = :rid
            WHERE id = :id
        """), {"human": _dumps(human), "now": _now(), "rv": new_version, "rid": new_id, "id": int(proposal_id)})
    _review_update(engine, row.get("review_id"), verdict=verdict, to_version=new_version, sections=sections)

    materialized = None
    try:
        materialized = service.ensure_materialized(engine, config_hash, agent_type, new_version, repo_root=repo_root,
                                                   is_margin_account=is_margin_account, materialized_by=CREATED_BY)
    except Exception as exc:     # noqa: BLE001 — the row is live; the tab rebuilds the dir on read
        materialized = {"error": f"{type(exc).__name__}: {exc}"}
    return service._json_safe({
        "proposal_id": int(proposal_id), "agent_type": agent_type, "version": new_version, "prompt_version_id": new_id,
        "previous_version": (change or {}).get("from_version"), "batch_id": (change or {}).get("batch_id"),
        "applied_on": target_n, "approved": sections["approved"], "rejected": sections["rejected"],
        "files": [{"id": c.id, "action": c.action, "kind": c.kind} for c in files],
        "materialized": materialized, "description": description,
    })


__all__ = [
    "ProposalError", "ProposalConflict", "NotConfigured", "FileChange", "ensure_schema", "list_proposals",
    "get_proposal", "start_draft", "run_pipeline", "apply_proposal", "reject_proposal", "prepare", "apply_patch",
    "verify_patch", "normalize_files", "derive_kind", "parse_llm_json", "field_order", "MAX_FILES",
]
