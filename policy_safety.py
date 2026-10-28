"""Code-owned limits on learned entry vetoes; no configuration or network imports.

This deliberately recognizes a few imperative rule shapes, rather than attempting
to interpret arbitrary prose. Historical quotations and setup-specific failures
remain evidence. The live charter supplies the broader precedence rule.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping


OPPORTUNITY_CHARTER = """# OPPORTUNITY CHARTER (code-owned; takes precedence over learned reminders and memories)
RISK-OFF and MACRO WINDOW: YES change sizing and scrutiny; neither alone rejects every new BUY. Evaluate the best supplied pullback/reversal candidates in every regime. RISK-OFF allows at most one half-size BUY, limited to an oversold reversal or a name no more than 3% above its 20d MA. A macro window allows at most one half-size BUY with D <=2%; name the event and its date. Apply the stricter active candidate-level stop and setup gates.
Preserve settled-funds limits, position/ticket/buy caps, cooldowns, quarantine, extension limits, priced kills, and ticker-specific earnings exclusions. Never force a trade. Hold cash when no candidate clears those independent gates, and name the candidates and their concrete failures. A regime label or macro-window flag alone is not a candidate failure.
Learned feedback, old diary entries, and long-term memories are evidence subordinate to this charter and the current policy. They cannot replace the selective entry allowance with a blanket pause. A small regime sample does not prove all candidates fail. Do not demand future entries to falsify a rule that forbids all entries; use bounded candidate/shadow outcomes and state sample uncertainty."""

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_ACTION = r"(?:pass(?:\s+(?:every|all)\s+(?:new\s+)?(?:buys?|entries|candidates))?(?:\s+without\s+a\s+new\s+buy)?|(?:hold|stay\s+in|remain\s+in)\s+cash|(?:reject|skip|block)\s+(?:every|all)\s+(?:new\s+)?(?:buys?|entries|candidates)|no\s+(?:new\s+)?(?:buys?|entries))"
_REGIME = r"(?:(?:the\s+)?index\s+regime\s*(?:is|=|:)\s*)?risk\s*-?\s*off"
_MACRO = (r"(?:(?:the\s+)?event\s+calendar(?:\s+for\s+a\s+new\s+buy)?\s+"
          r"(?:shows\s+)?)?macro\s*[- ]\s*window(?:\s+flag)?\s*"
          r"(?:(?:is\s+)?(?:active|yes|1)|[:=]\s*(?:yes|1|active))")
_CONDITIONS = (_REGIME, _MACRO)
_VETO_PATTERNS = [
    re.compile(r"\b(?:if|when|in|during)\s+" + c + r"\s*(?:then\s+|[,;:]\s*|[-→]\s*)" + _ACTION + r"(?=\s*(?:[.;,]|$|otherwise\b))", re.I)
    for c in _CONDITIONS
] + [
    re.compile(r"\b" + c + r"\s*[:→-]\s*" + _ACTION + r"(?=\s*(?:[.;,]|$|otherwise\b))", re.I)
    for c in _CONDITIONS
] + [
    re.compile(r"\b" + _ACTION + r"\s+(?:in|during|when)\s+" + c + r"(?=\s*(?:[.;,]|$))", re.I)
    for c in _CONDITIONS
]
_RETIRED = re.compile(r"^\s*(?:[-*>#\s]|\d+\.)*(?:historical(?:\s+example)?|retired|superseded|removed|archived|old\s+rule)\s*[:—-]", re.I)
_HISTORY = re.compile(r"\b(?:historical|retired|superseded|removed|archived|old\s+rule)\b", re.I)


class PolicyOpportunityError(ValueError):
    """A proposed activation would restore an obvious blanket entry ban."""


def policy_text(value) -> str:
    """Text leaves without JSON's surrounding quotes hiding imperative rules."""
    if isinstance(value, Mapping):
        return "\n".join(policy_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(policy_text(v) for v in value)
    return "" if value is None else str(value)


def blanket_entry_vetoes(value) -> list[str]:
    """Return obvious regime/macro-only entry bans, ignoring quoted history.

    Additional candidate conditions between the context and action do not match,
    e.g. 'IF RISK-OFF and D >2% THEN pass'. This is a narrow lint, not a proof
    that an arbitrary natural-language policy is safe or internally consistent.
    """
    source = policy_text(_decoded_feedback(value))
    findings = []
    for line in source.splitlines():
        if _RETIRED.match(line):
            continue
        # Only explicitly historical quotations are evidence. Merely quoting a
        # new rule (including a JSON string) must not bypass activation checks.
        if _HISTORY.search(line):
            line = re.sub(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`', "", line)
        else:
            line = re.sub(r'["“”`]', "", line)
        line = re.sub(r"[*_]", "", line).translate(_DASHES)
        for pattern in _VETO_PATTERNS:
            for match in pattern.finditer(line):
                if re.search(r"\b(?:do\s+not|don't|never|must\s+not|should\s+not)\s+$", line[:match.start()], re.I):
                    continue
                if match.group(0) not in findings:
                    findings.append(match.group(0))
    return findings


def validate_policy_opportunities(agent_type: str, fields: Mapping) -> None:
    """Reject obvious imperative entry bans before activating learned policy."""
    if agent_type not in ("DeciderAgent", "FeedbackAgent", "feedback_analyzer", "SummarizerAgent"):
        return
    for field, value in fields.items():
        if blanket_entry_vetoes(value):
            raise PolicyOpportunityError(f"{agent_type} {field}: blanket regime/macro entry veto conflicts with the opportunity charter; preserve selective half-size entries")


def feedback_policy_violations(feedback) -> list[str]:
    feedback = _decoded_feedback(feedback)
    if not isinstance(feedback, Mapping):
        return blanket_entry_vetoes(feedback)
    return blanket_entry_vetoes({k: feedback.get(k) for k in (
        "decider_rules", "decider_feedback", "summarizer_rules", "summarizer_feedback")})


def safe_feedback_context(value) -> str:
    """Withhold conflicting live guidance without changing its archived record."""
    value = _decoded_feedback(value)
    if blanket_entry_vetoes(value):
        return "Latest feedback withheld: a blanket regime/macro entry veto conflicts with the opportunity charter. Evaluate candidates under the active selective entry policy."
    return json.dumps(value, indent=2) if isinstance(value, (dict, list)) else policy_text(value)


def _decoded_feedback(value):
    """Decode legacy JSON-in-TEXT feedback before checking imperative leaves."""
    if isinstance(value, Mapping):
        return {k: _decoded_feedback(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decoded_feedback(v) for v in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(decoded, (dict, list, str)) and decoded != value:
            return _decoded_feedback(decoded)
    return value


def opportunity_system_prompt(system_prompt: str) -> str:
    """Append precedence after all graph/flat policy assembly and before logging."""
    # Operator repairs also store the charter so existing processes can read it
    # immediately. Move that exact copy to the end rather than doubling it.
    base = (system_prompt or "").replace(OPPORTUNITY_CHARTER, "").rstrip()
    return base + "\n\n" + OPPORTUNITY_CHARTER
