"""Two inspectable facets for the semantic atlas, independent of its geometry.

Market topics describe source content. Policy capabilities describe what a rule
does. A stop rule can therefore have a useful label without acquiring an Iran or
oil association. The primary family is a deterministic display choice, never a
causal claim, a trading instruction or a change to the underlying taxonomy.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re

from .taxonomy import HIERARCHY, VERSION as MARKET_VERSION, expand_topics, topic_metadata
from .themes import matches as market_matches

VERSION = "semantic_atlas_facets_v1_2026_10_29"

_FAMILIES = (
    ("policy_entries", "Entries & setups", "policy_capability", "#63e2c6", "Candidate selection, entry geometry, confirmation and re-entry conditions."),
    ("policy_risk", "Risk & exits", "policy_capability", "#ff7f99", "Stops, loss limits, exits and harvesting conditions."),
    ("policy_capital", "Capital & portfolio", "policy_capability", "#aab4ff", "Cash, position sizing, account limits and portfolio exposure."),
    ("policy_events", "Events & earnings", "policy_capability", "#ffc76e", "Event dates, earnings exposure, release timing and holding horizons."),
    ("policy_evidence", "Evidence quality", "policy_capability", "#76c7ff", "Ground truth, source provenance, ownership evidence and data limitations."),
    ("policy_learning", "Learning & feedback", "policy_capability", "#c792ea", "Hypothesis review, feedback, evaluation and policy-change discipline."),
    ("policy_identity", "Mission & identity", "policy_capability", "#8dd6b0", "Agent objectives, role, judgment style and shared principles."),
    ("market_geopolitics", "Geopolitics & trade", "market_topic", "#ffb16c", "Recorded conflict, Iran, sanctions, shipping and Hormuz references."),
    ("market_energy", "Energy & supply", "market_topic", "#f4cf67", "Recorded oil, gas, electricity and energy-supply discussion."),
    ("market_compute", "AI & compute", "market_topic", "#4edbd1", "Recorded AI, semiconductor, data-center and memory-production discussion."),
    ("market_technology", "Technology", "market_topic", "#7e9dff", "Recorded software, cloud and broader technology discussion."),
    ("market_mobility", "Mobility & EVs", "market_topic", "#a9d981", "Recorded electric-vehicle discussion or separately labeled issuer exposure."),
    ("market_corporate", "Corporate catalysts", "market_topic", "#ec95ca", "Explicit earnings, transactions, products and other company-event headlines."),
    ("market_macro", "Macro & economy", "market_topic", "#b8b1ed", "Explicit monetary-policy, inflation, labor and rates headlines."),
    ("market_other", "Other reports", "market_topic", "#7e9aad", "Saved observations with no sufficiently specific atlas family."),
)
_BY_ID = {ident: {"id": ident, "label": label, "facet": facet, "color": color, "description": description}
          for ident, label, facet, color, description in _FAMILIES}

# Title matches take precedence over incidental words in a long rule body.
# Words in a news summary never run through this capability classifier.
_POLICY_PATTERNS = (
    ("policy_entries", r"\b(?:regime gate|regime size|candidate\w*|entr(?:y|ies)|re[ -]?entr\w*|quarantine|extension cap|confirmation|setups?|pullbacks?|breakouts?|contrarian watchlist|watchlist)\b"),
    ("policy_risk", r"\b(?:priced kill|kill breach|loss cap|risk management|stops?|stop[ -]loss|exits?|harvest\w*|profit[ -]taking|drawdown|thesis break|unpriced holding)\b"),
    ("policy_capital", r"\b(?:capital|portfolio|position siz\w*|position limit\w*|account limits?|cash|settled funds?|buying power|correlation|exposure|allocation|whole[ -]shares?)\b"),
    ("policy_events", r"\b(?:events?|earnings|fomc|cpi|scheduled catalysts?|release timing|trading sessions?|holding horizon|calendar)\b"),
    ("policy_evidence", r"\b(?:ground truth|ownership|provenance|source quality|source origin|evidence|data availability|data quality|unavailable|not_shown|not shown|verification|verify|truthful|extraction patterns?|what the decider actually|market context|technical only|media manipulation|promotion)\b"),
    ("policy_learning", r"\b(?:learning|lessons?|feedback|review checks|review protocol|evaluation|falsif\w*|hypothes\w*|change discipline|policy change|patterns? to watch|reviewed promotion|visual framing research)\b"),
    ("policy_identity", r"\b(?:mission|identity|core philosophy|principles?|decision style|extraction style|shared purpose|objectives?|mandate)\b"),
)
_POLICY_RE = {ident: re.compile(pattern, re.I) for ident, pattern in _POLICY_PATTERNS}
_POLICY_ORDER = ["policy_risk", "policy_evidence", "policy_events", "policy_capital",
                 "policy_identity", "policy_learning", "policy_entries"]

_TOPIC_FAMILY = {
    "geopolitics": ("market_geopolitics", 3), "geopolitics_iran": ("market_geopolitics", 8),
    "geopolitics_conflict": ("market_geopolitics", 6), "geopolitics_sanctions": ("market_geopolitics", 7),
    "trade_shipping": ("market_geopolitics", 5), "shipping_hormuz": ("market_geopolitics", 10),
    "shipping_disruption": ("market_geopolitics", 6),
    "energy": ("market_energy", 3), "energy_oil": ("market_energy", 7),
    "technology": ("market_technology", 3), "ai": ("market_compute", 7),
    "semiconductors": ("market_compute", 8), "memory_manufacturing": ("market_compute", 9),
    "electric_vehicles": ("market_mobility", 8),
}
_EXTRA_MARKET_RE = {
    "market_macro": re.compile(r"\b(?:federal reserve|fed|fomc|inflation|consumer prices?|cpi|payrolls?|unemployment|jobs report|treasury yields?|bond yields?|interest rates?|central banks?|monetary policy|rate (?:cuts?|hikes?))\b", re.I),
    "market_corporate": re.compile(r"\b(?:earnings|quarterly results?|revenue|profit guidance|acquisitions?|mergers?|takeover|ipos?|initial public offering|product launch|new product|buybacks?|dividends?)\b", re.I),
}
_METADATA_LINE = re.compile(r"^(?:event calendar|macro window|event gate allowance|watchlist|index regime|sector[- ]etf)\s*:", re.I)


def atlas_catalog():
    """Return copies: editing a rendered legend cannot mutate classification."""
    return {"version": VERSION, "market_taxonomy_version": MARKET_VERSION,
            "facets": [{"id": "market_topic", "label": "Market topics"},
                       {"id": "policy_capability", "label": "Policy capabilities"}],
            "families": [dict(_BY_ID[ident]) for ident, *_ in _FAMILIES],
            "market_topics": [{"id": ident, "label": row["label"], **topic_metadata(ident)}
                              for ident, row in HIERARCHY.items()],
            "note": "Families color and label the measured text projection. They do not move points, verify news, assign causal credit or create trading rules."}


def _body(point):
    return str(point.get("body") or point.get("text") or "")[:24000]


def _terms(pattern, text):
    return sorted({match.group(0).lower() for match in pattern.finditer(text)})[:12]


def _capabilities(point):
    title = str(point.get("title") or "")[:400]
    # A stable ID can carry the heading when a minimal source omits its title.
    identifier = str(point.get("id") or "").replace("_", " ").replace(".", " ")
    body = _body(point)
    scores, evidence = {}, {}
    for ident, pattern in _POLICY_RE.items():
        titled, identified, content = _terms(pattern, title), _terms(pattern, identifier), _terms(pattern, body)
        heading = sorted(set(titled + identified))
        if heading or content:
            scores[ident] = 8 * len(heading) + len(content)
            evidence[ident] = {"basis": "title_terms" if titled else "identifier_terms" if identified else "body_terms",
                               "matched_terms": titled or identified or content}
    if scores:
        ranked = sorted(scores, key=lambda ident: (-scores[ident], _POLICY_ORDER.index(ident)))
        return ranked, evidence
    field = point.get("field")
    family = "policy_identity" if field == "soul" else "policy_learning" if field == "memory" else "policy_entries" if field == "strategy_directives" else "policy_evidence"
    return [family], {family: {"basis": "field_fallback", "matched_terms": [], "field": field}}


def _source_headlines(point):
    explicit = point.get("headlines")
    if isinstance(explicit, list):
        lines = [str(value).strip() for value in explicit[:3] if isinstance(value, str)]
    else:
        lines = _body(point).splitlines()[:3]
    # A summary's repetitive data-availability scaffolding is not a macro event.
    # A legacy one-line insight may follow fewer than three headlines. Avoid
    # letting its repeated FOMC/CPI availability checklist become a catalyst.
    lines = [re.split(r"\b(?:event calendar|macro window|event gate allowance)\s*:", line,
                      maxsplit=1, flags=re.I)[0]
             for line in lines if line.strip() and not _METADATA_LINE.match(line.strip())]
    return "\n".join(lines)[:4000]


def _market_families(point):
    headline_text, body = _source_headlines(point), _body(point)
    heading, content = market_matches(headline_text), market_matches(body)
    scores, evidence = {}, {}
    for topic, (family, weight) in _TOPIC_FAMILY.items():
        if topic in heading or topic in content:
            score = weight * (3 if topic in heading else 1)
            # Ancestor overlaps do not count as extra corroboration.
            if score > scores.get(family, 0):
                scores[family] = score
                evidence[family] = {"basis": "headline_terms" if topic in heading else "source_text_terms",
                                    "matched_terms": heading.get(topic) or content[topic], "topic_id": topic}
    # Macro/corporate extensions are display families based on substantive
    # headlines, not a silent rewrite of canonical market-topic IDs.
    for family, pattern in _EXTRA_MARKET_RE.items():
        terms = _terms(pattern, headline_text)
        if terms:
            scores[family] = 12
            evidence[family] = {"basis": "headline_terms", "matched_terms": terms,
                                "canonical_topic_id": None}
    recorded = point.get("market_themes") or []
    if isinstance(recorded, list):
        for topic in recorded:
            if topic in _TOPIC_FAMILY:
                family, _weight = _TOPIC_FAMILY[topic]
                if family not in scores:
                    scores[family] = 1
                    evidence[family] = {"basis": "recorded_market_topic", "matched_terms": [], "topic_id": topic}
    ranked = sorted(scores, key=lambda ident: (-scores[ident], list(_BY_ID).index(ident)))
    return ranked, evidence, heading, content


def annotate_atlas_points(points):
    """Annotate copied point records; coordinates, identities and source text survive.

    Guideline capability and market-topic facets remain independent. News never
    runs through the policy classifier merely because it mentions a stop or an
    unavailable quote. Kind is required for a source observation; omitted kind
    is the backwards-compatible guideline path.
    """
    result = []
    for raw in points or ():
        if not isinstance(raw, Mapping):
            raise TypeError("Atlas points must be mappings")
        point = deepcopy(dict(raw))
        kind = point.get("kind") or point.get("source_kind") or "guideline"
        recorded = point.get("market_themes") or []
        topics = expand_topics(topic for topic in recorded if topic in HIERARCHY) if isinstance(recorded, list) else []
        direct = market_matches(_body(point))
        topics = expand_topics([*topics, *direct]) or ["general"]
        if len(topics) > 1:
            topics = [ident for ident in topics if ident != "general"]
        capabilities = []
        if kind in ("news_observation", "feedback_hypothesis"):
            ranked, evidence, _heading, _content = _market_families(point)
            if ranked:
                family, assignment = ranked[0], evidence[ranked[0]]
                facet = "market_topic"
            elif kind == "feedback_hypothesis":
                family, facet = "policy_learning", "policy_capability"
                capabilities = [family]
                assignment = {"basis": "source_kind_feedback", "matched_terms": []}
            else:
                family, facet = "market_other", "market_topic"
                assignment = {"basis": "unclassified_source", "matched_terms": []}
        else:
            capabilities, evidence = _capabilities(point)
            family, facet = capabilities[0], "policy_capability"
            assignment = evidence[family]
        point.update(family_id=family, theme_id=family, color=_BY_ID[family]["color"],
                     family_label=_BY_ID[family]["label"], atlas_taxonomy_version=VERSION,
                     atlas_facets={"market_topics": topics, "policy_capabilities": capabilities,
                                   "market_paths": [{"id": ident, "label": HIERARCHY[ident]["label"], **topic_metadata(ident)}
                                                    for ident in topics]},
                     atlas_assignment={"facet": facet, **assignment, "primary_is_display_choice": True,
                                       "coordinates_unchanged": True})
        result.append(point)
    return result


__all__ = ["VERSION", "atlas_catalog", "annotate_atlas_points"]
