"""Agent memory text helpers (pure; no config, no database).

The memory field is Markdown: a YAML head, a header paragraph, standing sections (`## Lessons
Learned`, `## Patterns to Watch`, `## Mistakes to Avoid`), and a `## Log` of dated entries
(`## YYYY-MM-DD #tags`). Standing sections are policy and are never compressed; only the dated
diary entries are archived, oldest first, when the text exceeds the limit. Lines inside
`<!-- … -->` comments (the log template) are never treated as headings.

Until 2026-09-04 the compressor kept the header plus "the most recent sections that fit", which on
the first weekly run after the doctrine rewrite archived the Lessons / Patterns / Mistakes
sections of Decider v24 (6,161 → 3,916 chars) while keeping the diary.
"""
from __future__ import annotations

import re
from datetime import datetime

MAX_MEMORY_CHARS = 9000
DATED_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}")
ARCHIVE_NOTE = "*(Earlier log entries archived — {n} compressed)*"


def split_sections(text: str) -> list:
    """[(heading_line_or_None, body_lines)] — a heading starts a section unless inside a comment."""
    sections = []
    current: list = []
    heading = None
    in_comment = False
    for line in (text or "").split("\n"):
        stripped = line.strip()
        is_heading = line.startswith("## ") and not in_comment
        if is_heading:
            sections.append((heading, current))
            heading, current = line, []
            continue
        current.append(line)
        if "<!--" in stripped and "-->" not in stripped[stripped.index("<!--"):]:
            in_comment = True
        elif in_comment and "-->" in stripped:
            in_comment = False
    sections.append((heading, current))
    return sections


def _render(sections: list) -> str:
    parts = []
    for heading, body in sections:
        chunk = "\n".join(([heading] if heading is not None else []) + body)
        parts.append(chunk)
    return "\n".join(parts)


def compress_memory(text: str, max_chars: int = MAX_MEMORY_CHARS) -> str:
    """Archive the oldest dated log entries until the text fits; standing sections are untouched."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    sections = split_sections(text)
    dated = [i for i, (h, _b) in enumerate(sections) if h is not None and DATED_RE.match(h)]
    if not dated:
        return text          # nothing safe to archive
    # archive oldest first (document order; dated entries are appended chronologically)
    archived = 0
    kept = list(sections)
    for idx in dated:
        if len(_render([s for s in kept if s is not None])) <= max_chars:
            break
        kept[idx] = None
        archived += 1
    kept = [s for s in kept if s is not None]
    if archived:
        # note goes right after the first dated-container heading ("## Log") or at the end of the header
        note = ARCHIVE_NOTE.format(n=archived)
        placed = False
        for i, (h, body) in enumerate(kept):
            if h is not None and h.strip().lower().startswith("## log"):
                kept[i] = (h, body + ["", note])
                placed = True
                break
        if not placed:
            h0, b0 = kept[0]
            kept[0] = (h0, b0 + ["", note])
    return _render(kept).strip()


def append_dated_section(current_memory: str, new_lessons: str, *, today: datetime = None,
                         max_chars: int = MAX_MEMORY_CHARS) -> str:
    """current memory + "## <today>\\n<lessons>", then compress (diary only) to the limit."""
    body = (new_lessons or "").strip()
    base = (current_memory or "").strip()
    if not body:
        return base
    stamp = (today or datetime.now()).strftime("%Y-%m-%d")
    updated = f"{base}\n\n## {stamp}\n{body}".strip()
    if len(updated) > max_chars:
        updated = compress_memory(updated, max_chars)
    return updated


__all__ = ["MAX_MEMORY_CHARS", "split_sections", "compress_memory", "append_dated_section"]
