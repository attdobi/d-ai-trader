"""Decomposition of prompt_versions fields into policy-graph nodes (stdlib only).

Fidelity contract: every compiled field (strategy_directives / soul / memory) is cut into a
contiguous PARTITION of slices (R0–R6 below); each slice becomes one node whose
``sep_before + body + sep_after`` are the exact bytes of the slice, so
``''.join(node.text for node in compile_order)`` reproduces the stored text byte-for-byte.
Headings, numbering and bullets only decide WHERE the cuts fall and what the ids/titles are.
Templates (system_prompt / user_prompt_template) are single verbatim nodes.

Cut rules (all cuts at line starts, lines split on "\\n" only, "\\r" stays in the bytes):
  R0  protected regions — leading YAML block, <!-- --> comments, ``` fences: no cut inside.
  R1  "## " heading starts a level-2 slice.
  R2  a line exactly "---" (outside R0) ends the current slice inclusive; what follows is its
      own slice: kind identity (soul) / note (other fields).
  R3  title-block cut — only when the field has no H2 at all: a paragraph-initial, short,
      mostly-uppercase line (or "Latest Feedback Reminder:") starts a section.
  R4  child cuts inside a level-2 slice: numbered-rule runs (>= 2 items) and tag-bullet runs
      ("- **#tag" present) become children; plain bullet runs stay in the section body.
  R5  dated "## YYYY-MM-DD ..." headings are entries (parent = the "## Log" section if seen).
  R6  "## Latest Feedback Reminder ..." is the reminder section (id <field>.reminder).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import replace as dc_replace
from typing import Optional

from .model import (
    AGENT_DIR, AGENT_LABEL, AGENT_PREFIX, COMPILED_FIELDS, FIELD_DEFAULT_POLARITY, FIELD_SEGMENT,
    FIELD_TITLE, FIELDS, GraphBuild, InheritedText, LOCKED_LAST_SEGMENTS, Node, POLARITY_KEYWORDS,
    POLARITY_OVERRIDES, RowMeta, Slice, TEMPLATE_FIELDS, TEMPLATE_NODE_ID, actor_kind, normalize_heading,
    slug_for_heading, slugify, version_stamp,
)

# ----------------------------------------------------------------------------- regexes
H2_PREFIX = "## "
DATED_RE = re.compile(r"^## (\d{4})-(\d{2})-(\d{2})(.*)$")
NUM_ITEM_RE = re.compile(r"^\d+\. ")
BULLET_ITEM_RE = re.compile(r"^- ")
TAG_BULLET_RE = re.compile(r"^- \*\*#")
BOLD_LEAD_RE = re.compile(r"^- \*\*(.+?)\*\*")
RULE_LABEL_RE = re.compile(r"^(\d+)\. ([A-Z][A-Z0-9 /&\-\u2010-\u2013]{2,40}?)( — | – | - |: )")
RULE_TEXT_RE = re.compile(r"^\d+\. (.*)$")
REMINDER_LINE_RE = re.compile(r"^Latest Feedback Reminder:")
TAG_RE = re.compile(r"(?<![\w&/#])#([A-Za-z][A-Za-z0-9\-]*)")
WIKI_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
FENCE_RE = re.compile(r"```.*?```", re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([a-z_]+)\}(?!\})")
TITLE_EXCLUDED_STARTS = ("- ", "* ", "• ", ">", "{")
YAML_MAX_LINES = 60


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- line model
def _line_spans(text: str) -> list:
    """[(start, end)] per line; end includes the terminating "\\n" when present. "\\n" only."""
    spans, pos, n = [], 0, len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl == -1:
            spans.append((pos, n))
            break
        spans.append((pos, nl + 1))
        pos = nl + 1
    return spans


def _contents(text: str, spans: list) -> list:
    """Line text without the "\\n" terminator and without a trailing "\\r" (matching only)."""
    out = []
    for s, e in spans:
        c = text[s:e]
        if c.endswith("\n"):
            c = c[:-1]
        if c.endswith("\r"):
            c = c[:-1]
        out.append(c)
    return out


def _protected(contents: list) -> list:
    """R0: True for lines that start inside a protected region (YAML block, comment, fence)."""
    n = len(contents)
    prot = [False] * n
    yaml_end = -1
    if n and contents[0] == "---":
        for j in range(1, min(n, YAML_MAX_LINES + 1)):
            if contents[j] == "---":
                yaml_end = j
                break
    for i in range(yaml_end + 1):
        prot[i] = True
    in_comment = in_fence = False
    for i in range(yaml_end + 1, n):
        c = contents[i]
        if in_fence:
            prot[i] = True
            if c.lstrip().startswith("```"):
                in_fence = False
            continue
        if in_comment:
            prot[i] = True
        elif c.lstrip().startswith("```"):
            in_fence = True
            continue
        pos = 0
        while pos < len(c):
            if in_comment:
                k = c.find("-->", pos)
                if k == -1:
                    break
                in_comment, pos = False, k + 3
            else:
                k = c.find("<!--", pos)
                if k == -1:
                    break
                in_comment, pos = True, k + 4
    return prot


# ----------------------------------------------------------------------------- R3 helpers
def _title_core(line: str) -> str:
    t = re.sub(r"^[^\w]+", "", line.strip())
    if ":" in t:
        t = t.split(":", 1)[0]
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    return t.strip()


def _is_title_line(contents: list, i: int) -> bool:
    c = contents[i]
    if i > 0 and contents[i - 1].strip() != "":
        return False
    if not c or c[0].isspace():
        return False
    if REMINDER_LINE_RE.match(c):
        return True
    if len(c) > 90:
        return False
    if c.startswith(TITLE_EXCLUDED_STARTS) or re.match(r"^\d+\.", c):
        return False
    if c.rstrip().endswith("."):
        return False
    letters = [ch for ch in _title_core(c) if ch.isalpha()]
    if len(letters) < 2:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.6


# ----------------------------------------------------------------------------- R4 helpers
def _child_cuts(contents: list, prot: list, start: int, end: int) -> list:
    """Line indices (in [start, end)) that begin a child slice, with their kind.

    Returns [(line_index, kind)] for every item of every list that qualifies for splitting
    (numbered run with >= 2 items; bullet run containing a "- **#" item)."""
    cuts = []
    i = start
    while i < end:
        c = contents[i]
        if prot[i] or not (NUM_ITEM_RE.match(c) or BULLET_ITEM_RE.match(c)):
            i += 1
            continue
        numbered = bool(NUM_ITEM_RE.match(c))
        is_item = (lambda s: bool(NUM_ITEM_RE.match(s))) if numbered else (lambda s: bool(BULLET_ITEM_RE.match(s)))
        items = []
        j = i
        while j < end:
            cj = contents[j]
            if prot[j]:
                j += 1
                continue
            if is_item(cj):
                items.append(j)
                j += 1
                continue
            if cj.strip() == "":
                k = j + 1
                while k < end and contents[k].strip() == "" and not prot[k]:
                    k += 1
                if k < end and not prot[k] and (is_item(contents[k]) or contents[k][:1] in (" ", "\t")):
                    j = k
                    continue
                break
            j += 1
        if numbered:
            if len(items) >= 2:
                cuts.extend((p, "rule") for p in items)
        else:
            if any(TAG_BULLET_RE.match(contents[p]) for p in items):
                cuts.extend((p, "lesson") for p in items)
        i = max(j, i + 1)
    return cuts


# ----------------------------------------------------------------------------- slice_field
def slice_field(field: str, text: str) -> list:
    """R0–R6 partition of ``text`` into contiguous Slices covering [0, len(text)).

    The first slice is always the level-1 preamble (possibly empty); templates are one slice."""
    n = len(text)
    if field in TEMPLATE_FIELDS:
        return [Slice(0, n, 1, "template", "")]
    spans = _line_spans(text)
    contents = _contents(text, spans)
    prot = _protected(contents)
    nlines = len(spans)
    has_h2 = any(not prot[i] and contents[i].startswith(H2_PREFIX) for i in range(nlines))

    # level-2 segmentation in line indices: (start_line, end_line, kind, heading)
    segs = []
    cur_start, cur_kind, cur_heading = 0, "preamble", ""

    def close(end_line):
        segs.append((cur_start, end_line, cur_kind, cur_heading))

    for i in range(nlines):
        if prot[i]:
            continue
        c = contents[i]
        if c.startswith(H2_PREFIX):
            close(i)
            heading = c[3:].strip()
            if DATED_RE.match(c):
                kind = "entry"
            elif normalize_heading(heading).startswith("latest feedback reminder"):
                kind = "reminder"
            else:
                kind = "section"
            cur_start, cur_kind, cur_heading = i, kind, heading
            continue
        if c.rstrip() == "---":
            close(i + 1)
            cur_start, cur_kind, cur_heading = i + 1, ("identity" if field == "soul" else "note"), ""
            continue
        if not has_h2 and _is_title_line(contents, i):
            close(i)
            kind = "reminder" if REMINDER_LINE_RE.match(c) else "section"
            cur_start, cur_kind, cur_heading = i, kind, c.strip().rstrip(":").strip()
    close(nlines)

    def off(line_index):
        return spans[line_index][0] if line_index < nlines else n

    raw = []
    for idx, (ls, le, kind, heading) in enumerate(segs):
        s, e = off(ls), off(le)
        if idx == 0:
            raw.append(Slice(s, e, 1, "preamble", ""))
            continue
        if e <= s:
            continue
        has_heading_line = kind in ("section", "entry", "reminder")
        cuts = _child_cuts(contents, prot, ls + 1 if has_heading_line else ls, le)
        if not cuts:
            raw.append(Slice(s, e, 2, kind, heading))
            continue
        first = cuts[0][0]
        raw.append(Slice(s, off(first), 2, kind, heading))
        for k, (p, ckind) in enumerate(cuts):
            nxt = cuts[k + 1][0] if k + 1 < len(cuts) else le
            raw.append(Slice(off(p), off(nxt), 3, ckind, contents[p]))

    # whitespace-only slices merge into the previous slice (or the next one when first)
    kept = []
    for sl in raw:
        if kept and text[sl.start:sl.end].strip() == "":
            kept[-1] = dc_replace(kept[-1], end=sl.end)
            continue
        kept.append(sl)
    if len(kept) > 1 and kept[0].end > 0 and text[kept[0].start:kept[0].end].strip() == "":
        kept[1] = dc_replace(kept[1], start=0)
        kept[0] = dc_replace(kept[0], end=0)
    _assert_partition(kept, n)
    return kept


def _assert_partition(slices: list, n: int) -> None:
    if not slices:
        raise AssertionError("no slices")
    if slices[0].start != 0 or slices[-1].end != n:
        raise AssertionError("slices do not cover [0, len)")
    for a, b in zip(slices, slices[1:]):
        if a.end != b.start:
            raise AssertionError(f"slices not contiguous at {a.end} != {b.start}")
        if b.end < b.start:
            raise AssertionError("negative slice")


def split_seps(chunk: str) -> tuple:
    """(sep_before, body, sep_after): leading/trailing whitespace (str.isspace) around the body."""
    if chunk.strip() == "":
        return chunk, "", ""
    lead = len(chunk) - len(chunk.lstrip())
    trail = len(chunk) - len(chunk.rstrip())
    return chunk[:lead], chunk[lead:len(chunk) - trail], chunk[len(chunk) - trail:]


# ----------------------------------------------------------------------------- annotations
def _scan_text(body: str) -> str:
    """Body with comments, fences and code spans removed (tag / link scanning only)."""
    t = COMMENT_RE.sub(" ", body)
    t = FENCE_RE.sub(" ", t)
    return CODE_SPAN_RE.sub(" ", t)


def extract_tags(body: str) -> list:
    seen, out = set(), []
    for m in TAG_RE.finditer(_scan_text(body)):
        tag = m.group(1).lower()
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def extract_links(body: str) -> list:
    seen, out = set(), []
    for m in WIKI_RE.finditer(_scan_text(body)):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


def extract_tickers(body: str) -> list:
    scan = _scan_text(body)
    syms = set()
    for m in WIKI_RE.finditer(scan):
        t = m.group(1).strip()
        if TICKER_RE.match(t):
            syms.add(t)
    for m in TAG_RE.finditer(scan):
        if TICKER_RE.match(m.group(1)):
            syms.add(m.group(1))
    return sorted(syms)


def _first_tag_raw(line: str) -> Optional[str]:
    m = TAG_RE.search(line)
    return m.group(1) if m else None


def _first_sentence(body: str, limit: int = 80) -> str:
    first = body.strip().split("\n", 1)[0].strip()
    first = re.sub(r"^#+\s*", "", first)
    sent = re.split(r"(?<=[.!?])\s", first, 1)[0]
    return sent[:limit].rstrip()


def polarity_for(node_id: str, node_type: str, field: Optional[str], body: str, owner: str) -> tuple:
    """(polarity, polarity_source): override table (full id sans prefix / last segment / group
    segment for non-db owners) → keyword heuristic on the body → field default → mixed."""
    segs = node_id.split(".")
    keys = [".".join(segs[1:]), segs[-1]]
    if owner != "db" and owner != "default-file" and len(segs) > 2:
        keys.append(segs[1])
    if node_type in ("root", "template", "field"):
        keys.append(node_type)
    for k in keys:
        if k in POLARITY_OVERRIDES:
            return POLARITY_OVERRIDES[k], "override"
    for pol, rx in POLARITY_KEYWORDS:
        if rx.search(body):
            return pol, "heuristic"
    if field in FIELD_DEFAULT_POLARITY:
        return FIELD_DEFAULT_POLARITY[field], "heuristic"
    return "mixed", "heuristic"


def is_locked(node_id: str, node_type: str) -> bool:
    segs = node_id.split(".")
    if node_type in ("root", "code", "ltm", "data"):
        return True
    if len(segs) >= 2 and segs[1] in ("code", "ltm", "runtime"):
        return True
    if len(segs) >= 3 and segs[1] == "template" and segs[2] == "system":
        return True
    return segs[-1] in LOCKED_LAST_SEGMENTS


def _inert(agent_type: str, field: Optional[str]) -> bool:
    return agent_type == "FeedbackAgent" and field in ("system_prompt", "user_prompt_template",
                                                        "strategy_directives", "memory")


# ----------------------------------------------------------------------------- ids / titles
class _IdPool:
    def __init__(self):
        self.used = set()

    def take(self, candidate: str) -> str:
        if candidate not in self.used:
            self.used.add(candidate)
            return candidate
        k = 2
        while f"{candidate}_{k}" in self.used:
            k += 1
        out = f"{candidate}_{k}"
        self.used.add(out)
        return out


def _rule_title_and_slug(first_line: str, ordinal: int) -> tuple:
    m = RULE_LABEL_RE.match(first_line)
    if m:
        label = m.group(2).strip()
        return label, slugify(label)
    m2 = RULE_TEXT_RE.match(first_line)
    body = (m2.group(1) if m2 else first_line).strip()
    return body[:60].rstrip(), f"n{ordinal}"


def _lesson_title_and_slug(first_line: str, ordinal: int) -> tuple:
    m = BOLD_LEAD_RE.match(first_line)
    title = m.group(1).strip() if m else first_line[2:].strip()[:60].rstrip()
    if TAG_BULLET_RE.match(first_line):
        tag = _first_tag_raw(first_line)
        if tag:
            return title, slugify(tag)
    return title, f"n{ordinal}"


def _entry_slug(heading: str) -> str:
    m = DATED_RE.match("## " + heading)
    y, mo, d, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    slug = f"{y}_{mo}_{d}"
    tag = _first_tag_raw(rest)
    if tag:
        slug += "_" + slugify(tag)
    return slug


# ----------------------------------------------------------------------------- field → nodes
def _field_nodes(agent_type: str, field: str, text: str, *, owner: str, status: str, compiled: str,
                 provenance: str, extra: Optional[dict] = None, order_start: int = 0) -> list:
    """Nodes for one compiled field in document order (group node first)."""
    P = AGENT_PREFIX[agent_type]
    seg = FIELD_SEGMENT[field]
    group_id = f"{P}.{seg}"
    slices = slice_field(field, text)
    pool = _IdPool()
    pool.take(group_id)
    nodes = []
    order = order_start
    log_id = None
    section_id = None
    child_ordinal = 0

    def make(node_id, title, node_type, parent, chunk):
        nonlocal order
        sep_b, body, sep_a = split_seps(chunk)
        pol, src = polarity_for(node_id, node_type, field, body, owner)
        node = Node(
            id=node_id, agent=agent_type, title=title, node_type=node_type, parent=parent, field=field,
            body=body, sep_before=sep_b, sep_after=sep_a, order=order, polarity=pol, polarity_source=src,
            owner=owner, status=("inert" if _inert(agent_type, field) and status == "active" else status),
            compiled=compiled, locked=is_locked(node_id, node_type), provenance=provenance,
            tags=extract_tags(body), tickers=extract_tickers(body), links=extract_links(body),
            extra=dict(extra or {}),
        )
        order += 1
        nodes.append(node)
        return node

    for sl in slices:
        chunk = text[sl.start:sl.end]
        if sl.level == 1:
            make(group_id, FIELD_TITLE[field], "field", f"{P}.root", chunk)
            continue
        if sl.level == 2:
            child_ordinal = 0
            kind = sl.kind
            if kind == "entry":
                parent = log_id or group_id
                node_id = pool.take(f"{group_id}.log.{_entry_slug(sl.heading)}")
                make(node_id, sl.heading, "entry", parent, chunk)
                section_id = node_id
                continue
            if kind == "reminder":
                node_id = pool.take(f"{group_id}.reminder")
                title = sl.heading or "Latest Feedback Reminder"
                make(node_id, title, "reminder", group_id, chunk)
                section_id = node_id
                continue
            if kind in ("identity", "note"):
                node_id = pool.take(f"{group_id}.{kind}")
                sep_b, body, _ = split_seps(chunk)
                make(node_id, _first_sentence(body), kind, group_id, chunk)
                section_id = node_id
                continue
            slug = slug_for_heading(sl.heading)
            node_id = pool.take(f"{group_id}.{slug}")
            if slug == "log" and log_id is None:
                log_id = node_id
            make(node_id, sl.heading, "section", group_id, chunk)
            section_id = node_id
            continue
        # level 3
        child_ordinal += 1
        parent = section_id or group_id
        if sl.kind == "rule":
            title, slug = _rule_title_and_slug(sl.heading, child_ordinal)
        else:
            title, slug = _lesson_title_and_slug(sl.heading, child_ordinal)
        node_id = pool.take(f"{parent}.{slug}")
        make(node_id, title, sl.kind, parent, chunk)
    return nodes


# ----------------------------------------------------------------------------- generated bodies
def _root_body(agent_type: str, config_hash: str, version: int, meta: RowMeta, fields_meta: dict,
               n_code: int, n_ltm: int) -> str:
    label = AGENT_LABEL.get(agent_type, agent_type)
    created = str(meta.created_at)[:19] if meta.created_at is not None else "unknown time"
    parts = []
    for f in FIELDS:
        fm = fields_meta.get(f, {})
        if fm.get("stored_null"):
            state = "NULL"
        elif fm.get("inherited"):
            state = f"inherited from {fm.get('inherited_from')}"
        elif fm.get("stored_empty"):
            state = "empty"
        else:
            state = "stored"
        parts.append(f"{f}: {state}")
    if agent_type == "DeciderAgent":
        recipe = ("Runtime assembly (decider_agent.ask_decision_agent): system prompt = system_prompt template, "
                  "then '## AGENT IDENTITY' + soul, then strategy_directives substituted for "
                  "{strategy_directives} (appended when the placeholder is absent), then "
                  "'## LESSONS FROM EXPERIENCE' + memory; user prompt = user_prompt_template with the "
                  "per-cycle data blocks filled in, plus the code-owned blocks that fire for this version, "
                  "plus the long-term memory rows (decider_memory).")
    elif agent_type == "SummarizerAgent":
        recipe = ("Runtime assembly (main.get_openai_summary): system prompt = system_prompt template, then "
                  "'## AGENT IDENTITY' + soul, then strategy_directives substituted for {strategy_directives} "
                  "(appended when absent), then '## LESSONS FROM EXPERIENCE' + memory, then the "
                  "PERFORMANCE FEEDBACK suffix; user prompt = user_prompt_template filled per cycle.")
    elif agent_type == "CompanyExtractionAgent":
        recipe = ("Runtime assembly (decider_agent.extract_companies_from_summaries): system prompt = system_prompt "
                  "template, then '## AGENT IDENTITY' + soul, then strategy_directives substituted for "
                  "{strategy_directives} (appended when absent), then '## LESSONS FROM EXPERIENCE' + memory; user "
                  "prompt = user_prompt_template with the cycle's summaries filled in. Its tickers seed the "
                  "market-trends recap and the Decider's graph query (route 'entities').")
    else:
        recipe = ("Runtime assembly (feedback_agent._generate_ai_feedback): only the soul is injected "
                  "('## AGENT IDENTITY' after the hardcoded system base); the stored templates, "
                  "strategy_directives and memory are not executed by the weekly path.")
    return (f"{label} policy version {version} (config {config_hash}, prompt_versions#{meta.prompt_version_id}, "
            f"created {created} by {meta.created_by or 'unknown'} [{actor_kind(meta.created_by)}]"
            f"{' — ' + meta.description if meta.description else ''}). Fields: {'; '.join(parts)}. "
            f"Overlays: {n_code} code-owned block(s), {n_ltm} long-term memory row(s). {recipe}")


def _runtime_inputs_body(agent_type: str, fields: dict) -> str:
    user = fields.get("user_prompt_template") or ""
    placeholders = []
    for m in PLACEHOLDER_RE.finditer(user):
        if m.group(1) not in placeholders:
            placeholders.append(m.group(1))
    lines = ["Per-cycle data blocks — not policy text; varies per cycle.", ""]
    if placeholders:
        lines.append("Placeholders filled by safe_format_template from the user prompt template:")
        lines.extend(f"- {{{p}}}" for p in placeholders)
    else:
        lines.append("The user prompt template declares no {placeholder} fields.")
    if agent_type == "DeciderAgent":
        expected = ["holdings", "index_regime", "summaries", "momentum_recap", "feedback_context",
                    "settled_cash", "available_cash"]
        missing = [p for p in expected if p not in placeholders]
        lines.append("")
        lines.append("Blocks supplied by decider_agent.ask_decision_agent every cycle:")
        lines.append("- Holdings with K:/D: kill prices (RunContext / Schwab sync)")
        lines.append("- INDEX REGIME line (contrarian_screener.format_index_regime)")
        lines.append("- CONTRARIAN WATCHLIST rows (contrarian_screener.format_contrarian_watchlist)")
        lines.append("- QUARANTINE tickers (recently exited names)")
        lines.append("- # LESSONS rows (decider_memory.format_long_term_memory, weight/recency ranked)")
        lines.append("- # RECENT ACTIVITY (decider_memory.build_working_memory)")
        lines.append("- Feedback Snapshot (latest feedback row)")
        if missing:
            lines.append("")
            lines.append("# Auto-context lines appended for placeholders the template does not declare: "
                         + ", ".join("{" + p + "}" for p in missing))
    elif agent_type == "SummarizerAgent":
        lines.append("")
        lines.append("Blocks supplied by main.get_openai_summary every cycle: article text / screenshots, "
                     "portfolio holdings snapshot, PERFORMANCE FEEDBACK from the latest feedback row.")
    elif agent_type == "CompanyExtractionAgent":
        lines.append("")
        lines.append("Blocks supplied by decider_agent.extract_companies_from_summaries every cycle: the "
                     "Summarizers' headlines and insights (about six summaries), one block per summarizer.")
    else:
        lines.append("")
        lines.append("Blocks supplied by feedback_agent._generate_ai_feedback: closed-trade sample, computed "
                     "diagnostics, current prompts of the other agents, prior feedback.")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- decompose_row
def decompose_row(agent_type: str, config_hash: str, version: int, fields: dict, *, meta: RowMeta,
                  inherited: dict, code_nodes: list, ltm_nodes: list, is_margin_account: bool) -> GraphBuild:
    """Build the full node set for one prompt_versions row (edges are derived later)."""
    if agent_type not in AGENT_PREFIX:
        raise ValueError(f"unknown agent_type {agent_type!r}")
    P = AGENT_PREFIX[agent_type]
    root_id = f"{P}.root"
    provenance = f"prompt_versions#{meta.prompt_version_id}"
    inherited = inherited or {}
    nodes: list = []
    compile_order: dict = {}
    fields_meta: dict = {}

    # templates — single verbatim nodes
    for f in TEMPLATE_FIELDS:
        text = fields.get(f)
        fields_meta[f] = {"stored_null": text is None, "stored_empty": text == "", "inherited": False}
        if text is None:
            compile_order[f] = []
            continue
        node_id = f"{P}.{TEMPLATE_NODE_ID[f]}"
        pol, src = polarity_for(node_id, "template", f, text, "db")
        nodes.append(Node(
            id=node_id, agent=agent_type, title=FIELD_TITLE[f], node_type="template", parent=root_id, field=f,
            body=text, sep_before="", sep_after="", order=0, polarity=pol, polarity_source=src, owner="db",
            status=("inert" if _inert(agent_type, f) else "active"), compiled="stored",
            locked=is_locked(node_id, "template"), provenance=provenance,
            tags=extract_tags(text), tickers=extract_tickers(text), links=extract_links(text),
        ))
        compile_order[f] = [node_id]

    # compiled fields
    for f in COMPILED_FIELDS:
        text = fields.get(f)
        fm = {"stored_null": text is None, "stored_empty": text == "", "inherited": False}
        inh = inherited.get(f)
        use_inherited = (not text) and isinstance(inh, InheritedText) and bool(inh.text)
        if use_inherited:
            compile_order[f] = []
            inh_nodes = _field_nodes(
                agent_type, f, inh.text, owner="default-file", status="inherited", compiled="effective-only",
                provenance=f"{inh.source_path}@{inh.git_sha or 'worktree'}",
                extra={"inherited_from": inh.source_path, "inherited_git_sha": inh.git_sha,
                       "inherited_resolution": inh.resolution},
            )
            nodes.extend(inh_nodes)
            fm.update({
                "inherited": True, "inherited_from": inh.source_path, "inherited_git_sha": inh.git_sha,
                "inherited_resolution": inh.resolution, "inherited_sha256": sha256_text(inh.text),
                "inherited_order": [n.id for n in inh_nodes],
            })
        elif text is None:
            compile_order[f] = []
        else:
            db_nodes = _field_nodes(agent_type, f, text, owner="db", status="active", compiled="stored",
                                    provenance=provenance)
            nodes.extend(db_nodes)
            compile_order[f] = [n.id for n in db_nodes]
        fields_meta[f] = fm

    # overlays
    code_nodes = list(code_nodes or [])
    ltm_nodes = list(ltm_nodes or [])
    code_group = f"{P}.code"
    ltm_group = f"{P}.ltm"
    passed_groups = {n.id for n in code_nodes + ltm_nodes if n.id in (code_group, ltm_group)}

    root_pol, root_src = polarity_for(root_id, "root", None, "", "generated")
    root = Node(
        id=root_id, agent=agent_type, title=f"{AGENT_LABEL.get(agent_type, agent_type)} policy v{version}",
        node_type="root", parent=None, field=None,
        body=_root_body(agent_type, config_hash, version, meta, fields_meta,
                        len([n for n in code_nodes if n.id != code_group]),
                        len([n for n in ltm_nodes if n.id != ltm_group])),
        order=0, polarity=root_pol, polarity_source=root_src, owner="generated", status="generated",
        compiled="never", locked=True, provenance="generated",
    )

    rt_id = f"{P}.runtime.inputs"
    runtime = Node(
        id=rt_id, agent=agent_type, title="Per-cycle runtime inputs", node_type="data", parent=root_id,
        field=None, body=_runtime_inputs_body(agent_type, fields), order=0, polarity="structure",
        polarity_source="override", owner="runtime", status="generated", compiled="never", locked=True,
        provenance="generated",
    )

    out = [root] + nodes + [runtime]

    if code_nodes:
        if code_group not in passed_groups:
            out.append(Node(
                id=code_group, agent=agent_type, title="Code-owned prompt blocks", node_type="section",
                parent=root_id, field=None,
                body=("Prompt text that lives in Python source (verbatim copies from policy_graph.code_blocks). "
                      "Read-only here; edit the source and the drift test."),
                order=0, polarity="structure", polarity_source="override", owner="generated", status="generated",
                compiled="never", locked=True, provenance="generated",
            ))
        for k, cn in enumerate(code_nodes):
            if cn.id == code_group:
                cn.parent = root_id
                out.append(cn)
                continue
            cn.parent = code_group
            cn.agent = agent_type
            cn.order = k + 1
            out.append(cn)

    if ltm_nodes:
        if ltm_group not in passed_groups:
            out.append(Node(
                id=ltm_group, agent=agent_type, title="Long-term memory rows (decider_memory)", node_type="ltm",
                parent=root_id, field=None,
                body="Rows of the decider_memory table injected into the user prompt as # LESSONS (read-only snapshot).",
                order=0, polarity="evidence", polarity_source="override", owner="decider_memory",
                status="generated", compiled="never", locked=True, provenance="decider_memory",
            ))
        for k, ln in enumerate(ltm_nodes):
            if ln.id == ltm_group:
                ln.parent = root_id
                out.append(ln)
                continue
            ln.parent = ltm_group
            ln.agent = agent_type
            ln.order = k + 1
            out.append(ln)

    ids = {n.id for n in out}
    for n in out:
        if n.id != root_id and n.parent not in ids:
            raise AssertionError(f"node {n.id} has missing parent {n.parent}")
    return GraphBuild(nodes=out, edges=[], compile_order=compile_order, fields_meta=fields_meta, root_id=root_id)


# ----------------------------------------------------------------------------- node <-> frontmatter
_NODE_SCALAR_KEYS = ("id", "agent", "title", "node_type", "polarity", "polarity_source", "parent", "field",
                     "order", "owner", "status", "compiled", "locked", "provenance", "sep_before", "sep_after")
_CONSUMED_KEYS = set(_NODE_SCALAR_KEYS) | {"version", "body_sha256", "tags", "tickers", "edges", "links"}


def node_to_frontmatter(node: Node, version_stamp: str) -> dict:
    fm = {
        "id": node.id,
        "version": version_stamp,
        "agent": node.agent,
        "title": node.title,
        "node_type": node.node_type,
        "polarity": node.polarity,
        "polarity_source": node.polarity_source,
        "parent": node.parent,
        "field": node.field,
        "order": int(node.order),
        "owner": node.owner,
        "status": node.status,
        "compiled": node.compiled,
        "locked": bool(node.locked),
        "provenance": node.provenance,
        "sep_before": node.sep_before,
        "sep_after": node.sep_after,
        "body_sha256": sha256_text(node.body),
        "tags": list(node.tags),
        "tickers": list(node.tickers),
    }
    for k, v in (node.extra or {}).items():
        if k in _CONSUMED_KEYS:
            continue
        fm[k] = v
    if node.edges:
        fm["edges"] = [dict(e) for e in node.edges]
    return fm


class NodeIntegrityError(ValueError):
    """body_sha256 in the frontmatter does not match the body bytes read back."""


def node_from_frontmatter(fm: dict, body: str) -> Node:
    if "id" not in fm:
        raise ValueError("frontmatter without id")
    expected = fm.get("body_sha256")
    if expected and expected != sha256_text(body):
        raise NodeIntegrityError(f"{fm['id']}: body_sha256 mismatch")

    def s(key, default=""):
        v = fm.get(key, default)
        return default if v is None else str(v)

    parent = fm.get("parent")
    field = fm.get("field")
    order = fm.get("order", 0)
    try:
        order = int(order or 0)
    except (TypeError, ValueError):
        order = 0
    node = Node(
        id=str(fm["id"]), agent=s("agent"), title=s("title"), node_type=s("node_type", "note"),
        parent=(str(parent) if parent is not None else None), field=(str(field) if field is not None else None),
        body=body, sep_before=s("sep_before"), sep_after=s("sep_after"), order=order,
        polarity=s("polarity", "mixed"), polarity_source=s("polarity_source", "heuristic"),
        owner=s("owner", "db"), status=s("status", "active"), compiled=s("compiled", "stored"),
        locked=bool(fm.get("locked", False)), provenance=s("provenance"),
        tags=[str(t) for t in (fm.get("tags") or [])], tickers=[str(t) for t in (fm.get("tickers") or [])],
        links=extract_links(body),
        extra={k: v for k, v in fm.items() if k not in _CONSUMED_KEYS},
        edges=[dict(e) for e in (fm.get("edges") or [])],
    )
    return node


__all__ = [
    "slice_field", "decompose_row", "node_to_frontmatter", "node_from_frontmatter", "NodeIntegrityError",
    "split_seps", "extract_tags", "extract_links", "extract_tickers", "polarity_for", "sha256_text",
    "version_stamp", "AGENT_DIR",
]
