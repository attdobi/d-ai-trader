"""Bounded operator calendar context for news summaries; no model or broker calls.

One sweep freezes this local macro-only snapshot for all news sources. It is
provided context, never evidence that a publisher mentioned or verified an event.
Company earnings and portfolio-dependent controls remain Decider enrichment.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import os
from zoneinfo import ZoneInfo

VERSION = "summary_macro_calendar_v1"
_ROLE = "provided_operator_context_not_news_observation"
_ET = ZoneInfo("America/New_York")
SUMMARY_CALENDAR_HEADER = "# OPERATOR MACRO CALENDAR — code context, not news evidence"
SUMMARY_CALENDAR_RULES = """Use this as operator_calendar context in the existing EVENT CALENDAR sentence; distinguish it from facts observed in the news source. A supplied date does not mean an article mentioned it or that a company claim is verified.
This block supplies no index regime, portfolio risk score, ownership, company earnings dates or trade-sizing allowance. Unprovided company/event details remain not_shown; the Decider enriches and applies the current approved controls later.
A macro-window flag alone neither rejects every opportunity nor orders a trade. Preserve the existing headline/card JSON contract and insights word budget; do not add fields for this block."""
_EVENT_FIELDS = ("label", "next", "sessions_to", "last", "sessions_since", "release_et", "phase",
                 "in_window", "just_printed", "calendar_exhausted")


def _date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _integer(value):
    return value if type(value) is int and abs(value) <= 10000 else None


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _event(raw, label):
    raw = raw if isinstance(raw, dict) else {}
    return {"label": label, "next": _date(raw.get("next")),
            "sessions_to": _integer(raw.get("sessions_to")), "last": _date(raw.get("last")),
            "sessions_since": _integer(raw.get("sessions_since")),
            "release_et": _text(raw.get("release_et"), 24) or None,
            "phase": raw.get("phase") if raw.get("phase") in ("pre", "post") else None,
            "in_window": raw.get("in_window") is True,
            "just_printed": raw.get("just_printed") is True,
            "calendar_exhausted": raw.get("calendar_exhausted") is True}


def freeze_summary_calendar(as_of=None, *, calendar=None):
    """Freeze pure local calendar facts; unavailable data never creates a regime.

    ``calendar`` is a test seam for the public local-calendar functions. Production
    uses their current built-in/operator-file dates without earnings lookup, SQL,
    provider requests, portfolio access or score computation.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    et = now.astimezone(_ET)
    out = {"version": VERSION, "evidence_role": _ROLE,
           "as_of_utc": now.isoformat().replace("+00:00", "Z"), "as_of_et": et.isoformat(),
           "available": False, "status": "unavailable", "macro_window": None,
           "macro_reason": None, "events": {}, "other": [], "other_omitted": 0,
           "coverage": {"horizon_end": None, "gaps": []}}
    if os.getenv("DAI_EVENT_CALENDAR_ENABLED", "1") in ("0", "false", "False"):
        out["status"] = "disabled"
    else:
        try:
            if calendar is None:
                import event_calendar as calendar
            statuses = calendar.macro_statuses(et.date(), et.time())
            in_window, reason = calendar.macro_window(statuses)
            coverage = calendar.calendar_coverage(et.date())
            out.update(available=True, status="available", macro_window=bool(in_window),
                       macro_reason=_text(reason, 200) or None,
                       events={key: _event(statuses.get(key), label) for key, label in
                               (("fomc", "FOMC decision"), ("cpi", "CPI"), ("jobs", "jobs report"))})
            other = statuses.get("other") or []
            out["other"] = [_event(raw, _text(raw.get("label"), 80))
                            for raw in other[:4] if isinstance(raw, dict)]
            out["other_omitted"] = max(0, len(other) - 4)
            out["coverage"] = {"horizon_end": _date(coverage.get("horizon_end")),
                "gaps": [{"kind": gap.get("kind"), "last": _date(gap.get("last"))}
                         for gap in (coverage.get("gaps") or [])[:2]
                         if isinstance(gap, dict) and gap.get("kind") in ("cpi", "jobs")]}
        except Exception:
            # Driver/provider/path diagnostics must not enter prompts or saved metadata.
            out.update(available=False, status="unavailable", macro_window=None,
                       macro_reason=None, events={}, other=[], other_omitted=0,
                       coverage={"horizon_end": None, "gaps": []})
    out["context_id"] = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return out


def summary_calendar_metadata(context):
    """Copy the internally built allowlisted context, separate from model output."""
    out = {key: deepcopy(context.get(key)) for key in
           ("version", "evidence_role", "as_of_utc", "as_of_et", "available", "status",
            "macro_window", "macro_reason", "other_omitted", "context_id")}
    out["events"] = {key: {field: deepcopy(row.get(field)) for field in _EVENT_FIELDS}
                     for key, row in (context.get("events") or {}).items()
                     if key in ("fomc", "cpi", "jobs") and isinstance(row, dict)}
    out["other"] = [{field: deepcopy(row.get(field)) for field in _EVENT_FIELDS}
                    for row in (context.get("other") or [])[:4] if isinstance(row, dict)]
    coverage = context.get("coverage") or {}
    out["coverage"] = {"horizon_end": coverage.get("horizon_end"),
                       "gaps": [{"kind": row.get("kind"), "last": row.get("last")}
                                for row in (coverage.get("gaps") or [])[:2] if isinstance(row, dict)]}
    return out


def render_summary_calendar(context):
    """A compact operator-data block; never asks for extra JSON keys or words."""
    lines = [SUMMARY_CALENDAR_HEADER,
             f"Context {context['context_id']} | as of {context['as_of_utc']} / {context['as_of_et']} ET"]
    if not context.get("available"):
        lines.append("Calendar context is " + context.get("status", "unavailable") + "; do not infer missing dates or a macro-window flag.")
    else:
        lines.append("MACRO WINDOW: " + ("YES" if context["macro_window"] else "NO")
                     + (" | " + context["macro_reason"] if context.get("macro_reason") else ""))
        for event in [*context["events"].values(), *context["other"]]:
            lines.append(f"- {event['label']}: next {event['next'] or 'not_in_calendar'}; sessions-to {event['sessions_to'] if event['sessions_to'] is not None else 'unknown'}; "
                         f"last {event['last'] or 'not_in_calendar'}; sessions-since {event['sessions_since'] if event['sessions_since'] is not None else 'unknown'}; "
                         f"release {event['release_et'] or 'unknown'}; today's release phase {event['phase'] or 'not_applicable'}")
        if context["other_omitted"]:
            lines.append(f"{context['other_omitted']} additional operator events omitted from this bounded block.")
        coverage = context["coverage"]
        lines.append("Coverage checked through " + str(coverage["horizon_end"] or "unknown") + ": "
                     + ("; ".join(f"{gap['kind']} dates end {gap['last'] or 'unknown'}" for gap in coverage["gaps"])
                        if coverage["gaps"] else "no reported CPI/jobs coverage gap"))
    lines.append(SUMMARY_CALENDAR_RULES)
    return "\n".join(lines)
