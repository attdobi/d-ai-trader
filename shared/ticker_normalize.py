"""Canonical ticker normalization helpers shared across modules."""

from __future__ import annotations

import re
from typing import Mapping, Optional

_RANK_PREFIX_RE = re.compile(r"^R(\d+)\s*[-_:/\\\s]+(.+)$", re.IGNORECASE)


def normalize_ticker(raw: str, alias_map: Optional[Mapping[str, str]] = None) -> str:
    """Return a cleaned, canonical ticker symbol.

    Behavior is intentionally small and backward-compatible:
    - non-string / empty values -> ""
    - trims whitespace and uppercases
    - strips rank prefixes (e.g. ``R1-TSLA``, ``r2/TSLA``)
    - optionally applies an alias map for known symbol drifts
    """
    if not isinstance(raw, str):
        return ""

    cleaned = raw.strip().upper()
    if not cleaned:
        return ""

    match = _RANK_PREFIX_RE.match(cleaned)
    if match:
        cleaned = match.group(2).strip().upper()

    if alias_map:
        normalized_aliases = {
            str(src).strip().upper(): str(dst).strip().upper()
            for src, dst in alias_map.items()
        }
        cleaned = normalized_aliases.get(cleaned, cleaned)

    return cleaned
