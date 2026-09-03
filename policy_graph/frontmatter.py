"""Strict byte-exact node file writer/reader.

File bytes = b"---\n" + frontmatter lines + b"\n---\n" + body (utf-8, verbatim).
The reader takes everything after the FIRST b"\n---\n" following the opening fence as the body,
so a body that itself starts with "---\n" (a memory YAML block) round-trips: frontmatter lines
never equal "---" (every key line is "key: value").

Scalars are written bare when safe, else JSON-encoded (that is how sep_before: "\n\n" survives);
lists inline; `edges:` as RUSH inline maps `- {type: X, to: Y}`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

KEY_ORDER = [
    "id", "version", "agent", "title", "node_type", "polarity", "polarity_source", "parent", "field", "order",
    "owner", "status", "compiled", "locked", "provenance", "sep_before", "sep_after", "body_sha256",
    "tags", "tickers",
    "inherited_from", "inherited_git_sha", "inherited_resolution",
    "source_file", "source_symbol", "source_lines", "code_sha", "git_sha", "condition", "fires", "position",
    "kind", "source", "weight", "ticker", "row_created_at", "row_updated_at", "injected", "active",
    "edges",
]
_BARE_RE = re.compile(r"^[A-Za-z0-9_.\-/#@:+]+$")
_LEADING_MARKER_RE = re.compile(r"^(?:\s*<!--\s*[^>]*?\.md\s*-->\s*\n)+")


class FrontmatterError(ValueError):
    pass


def format_scalar(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    s = str(value)
    if (s and _BARE_RE.match(s) and not s.startswith("#") and s not in ("true", "false", "null")
            and not re.match(r"^-?\d+(\.\d+)?$", s)):
        return s
    return json.dumps(s, ensure_ascii=False)


def parse_scalar(raw: str):
    v = raw.strip()
    if v == "":
        return ""
    if v.startswith('"'):
        return json.loads(v)
    if v == "null" or v == "~":
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if re.match(r"^-?\d+$", v):
        return int(v)
    if re.match(r"^-?\d+\.\d+$", v):
        return float(v)
    if (v.startswith("'") and v.endswith("'")) and len(v) >= 2:
        return v[1:-1]
    return v


def _format_list(values) -> str:
    return "[" + ", ".join(format_scalar(v) for v in values) + "]"


def _parse_list(raw: str) -> list:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    out, buf, in_str, esc = [], "", False, False
    for ch in inner:
        if in_str:
            buf += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            buf += ch
        elif ch == ",":
            out.append(parse_scalar(buf))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(parse_scalar(buf))
    return out


def format_inline_map(mapping: dict) -> str:
    return "{" + ", ".join(f"{k}: {format_scalar(v)}" for k, v in mapping.items()) + "}"


def parse_inline_map(raw: str) -> dict:
    """RUSH port: `{type: subtype_of, to: GA.root, via: "…"}` → dict (values may be JSON strings)."""
    s = raw.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise FrontmatterError(f"not an inline map: {raw!r}")
    inner = s[1:-1]
    out, key, buf, in_str, esc, reading_key = {}, "", "", False, False, True
    for ch in inner:
        if in_str:
            buf += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if reading_key:
            if ch == ":":
                key = buf.strip()
                buf = ""
                reading_key = False
            else:
                buf += ch
        else:
            if ch == '"':
                in_str = True
                buf += ch
            elif ch == ",":
                out[key] = parse_scalar(buf)
                buf, key, reading_key = "", "", True
            else:
                buf += ch
    if key:
        out[key] = parse_scalar(buf)
    return out


def render_frontmatter(fm: dict) -> str:
    """Ordered frontmatter text (no fences). Unknown keys are appended after KEY_ORDER."""
    lines = []
    keys = [k for k in KEY_ORDER if k in fm] + [k for k in fm if k not in KEY_ORDER]
    for k in keys:
        v = fm[k]
        if k == "edges":
            lines.append("edges:")
            for e in v or []:
                lines.append("  - " + format_inline_map(e))
        elif isinstance(v, (list, tuple)):
            lines.append(f"{k}: {_format_list(v)}")
        elif isinstance(v, dict):
            lines.append(f"{k}: {format_inline_map(v)}")
        else:
            lines.append(f"{k}: {format_scalar(v)}")
    return "\n".join(lines)


def parse_frontmatter_text(text: str) -> dict:
    fm, current_list_key = {}, None
    for line in text.split("\n"):
        if not line.strip():
            continue
        if current_list_key is not None and line.startswith("  - "):
            fm[current_list_key].append(parse_inline_map(line[4:]))
            continue
        current_list_key = None
        m = re.match(r"^([A-Za-z_][\w-]*):(.*)$", line)
        if not m:
            raise FrontmatterError(f"bad frontmatter line: {line!r}")
        key, raw = m.group(1), m.group(2)
        if raw.strip() == "" and key == "edges":
            fm[key] = []
            current_list_key = key
        elif raw.strip().startswith("[") and raw.strip().endswith("]"):
            fm[key] = _parse_list(raw)
        elif raw.strip().startswith("{") and raw.strip().endswith("}"):
            fm[key] = parse_inline_map(raw)
        else:
            fm[key] = parse_scalar(raw)
    return fm


def write_node(path: Path, fm: dict, body: str) -> bytes:
    data = b"---\n" + render_frontmatter(fm).encode("utf-8") + b"\n---\n" + body.encode("utf-8")
    path = Path(path)
    with open(path, "wb") as fh:
        fh.write(data)
    return data


def read_node_bytes(data: bytes) -> tuple[dict, str]:
    if not data.startswith(b"---\n"):
        raise FrontmatterError("node file must start with '---\\n' (leading markers are not allowed in stored nodes)")
    idx = data.find(b"\n---\n", 4)
    if idx == -1:
        raise FrontmatterError("closing frontmatter fence not found")
    fm_text = data[4:idx].decode("utf-8")
    body = data[idx + 5:].decode("utf-8")
    return parse_frontmatter_text(fm_text), body


def read_node(path: Path) -> tuple[dict, str]:
    with open(path, "rb") as fh:
        return read_node_bytes(fh.read())


def strip_leading_markers(text: str) -> str:
    """RUSH port — drafter LLMs echo the '<!-- name.md -->' bundle marker; strip it (proposal path only)."""
    return _LEADING_MARKER_RE.sub("", text or "", count=1)


def atomic_write_text(path: Path, text: str) -> None:
    tmp = Path(str(path) + f".{os.getpid()}.part")
    with open(tmp, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
