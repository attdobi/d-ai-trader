"""Auditable market-topic annotations for the Learning map.

These deterministic labels describe recorded words, not hidden intent, a causal
market driver, or an LLM decision boundary. Generic policy rules stay general
unless their own text names a topic or a same-version cited case supplies one.
Nothing here changes policy text, embeddings, coordinates, actions or quality
denominators. No market-data, database or model access is performed.
"""
from __future__ import annotations

from collections import defaultdict
import re

from .taxonomy import HIERARCHY, VERSION, expand_topics, topic_metadata


METHOD_ID = "market_themes_v2"
ISSUER_REFERENCE_ID = "issuer_theme_exposure_2026_10_28_v1"

# A small versioned browsing aid, not live sector-master data. Membership means
# issuer/industry exposure; it never establishes today's catalyst or causation.
# GM/F include substantial combustion-engine businesses; WDC is storage rather
# than a claim that it manufactures DRAM/NAND after its flash-business split.
ISSUER_THEMES = {
    "TSLA": ("technology", "electric_vehicles"), "RIVN": ("electric_vehicles",),
    "GM": ("electric_vehicles",), "F": ("electric_vehicles",),
    "MU": ("technology", "semiconductors", "memory_manufacturing"),
    "SNDK": ("technology", "semiconductors", "memory_manufacturing"),
    "WDC": ("technology",),
    "NVDA": ("technology", "ai", "semiconductors"),
    "AMD": ("technology", "ai", "semiconductors"),
    "INTC": ("technology", "semiconductors"), "TSM": ("technology", "semiconductors"),
    "MSFT": ("technology", "ai"), "GOOG": ("technology", "ai"),
    "GOOGL": ("technology", "ai"), "AMZN": ("technology", "ai"),
    "META": ("technology", "ai"), "ORCL": ("technology", "ai"),
    "AAPL": ("technology",), "NFLX": ("technology",),
    "XOM": ("energy_oil",), "CVX": ("energy_oil",), "OXY": ("energy_oil",),
    "COP": ("energy_oil",), "SLB": ("energy_oil",),
}

# Deliberately small, inspectable vocabulary. In particular, bare "memory" is
# prompt memory, not evidence about DRAM/NAND production; bare "EV" can mean
# enterprise value, and an oil/defense ticker does not establish an Iran event.
_TOPICS = (
    ("geopolitics", "Geopolitics", "Explicit geopolitical references; geography may be unspecified.",
     r"\bgeopolitic\w*\b"),
    ("geopolitics_iran", "Iran / Middle East", "Explicit Iran or Middle East references, including risks and denials.",
     r"\b(?:iran(?:ian)?|strait of hormuz|straight of hormuz|hormuz|middle east)\b"),
    ("geopolitics_conflict", "Conflict / diplomacy", "Explicit military conflict, ceasefire and diplomatic references.",
     r"\b(?:armed conflict|ceasefire|military strike\w*|diplomat\w*)\b|(?<!price )(?<!bidding )\bwar\b"),
    ("geopolitics_sanctions", "Sanctions / restrictions", "Recorded economic sanctions, embargoes or trade restrictions.",
     r"\b(?:sanctions?|embargo\w*|export controls?|trade restrictions?)\b"),
    ("trade_shipping", "Trade / shipping", "Explicit shipping, freight or supply-chain references.",
     r"\b(?:shipping|freight|supply.chain\w*|tankers?)\b"),
    ("shipping_hormuz", "Strait of Hormuz", "Explicit Hormuz references, including discussion of potential disruption.",
     r"\b(?:(?:strait|straight) of hormuz|hormuz)\b"),
    ("shipping_disruption", "Shipping / supply disruption", "Recorded shipping-route, port or supply disruption references.",
     r"\b(?:shipping (?:routes?|disrupt\w*)|supply disrupt\w*|port closures?|tanker traffic|red sea|suez canal|bab.el.mandeb)\b"),
    ("energy", "Energy", "Broad energy and electricity-market references.",
     r"\b(?:energy|electricity|power grids?|power generation|power demand)\b"),
    ("energy_oil", "Oil / gas", "Oil, gas and fuel-market references.",
     r"\b(?:oil|crude|brent|wti|opec\+?|natural gas|petroleum|refiner\w*|fuel|lng)\b"),
    ("technology", "Technology", "Technology, software, cloud and computing references.",
     r"\b(?:tech(?:nology)?|software|cloud|comput(?:e|ing) (?:capacity|infrastructure|demand|chips?|hardware)|data cent(?:er|re)s?|semiconductors?|chip(?:s|maker\w*)?|artificial intelligence|ai|electric vehicles?|electric cars?)\b"),
    ("ai", "AI", "Explicit artificial intelligence, model or AI infrastructure references.",
     r"\b(?:ai|artificial intelligence|machine learning|llms?|generative ai|gpu\w*|ai infrastructure|(?:ai|model) inference|inference (?:infrastructure|workloads?|chips?)|training cluster\w*)\b"),
    ("semiconductors", "Semiconductors", "Chip design, fabrication and semiconductor references.",
     r"\b(?:semiconductors?|chip(?:s|maker\w*)?|foundr(?:y|ies)|wafer\w*|gpu\w*|dram|nand|hbm|memory chips?)\b"),
    ("memory_manufacturing", "Memory manufacturing", "DRAM, NAND, HBM and memory-chip production references.",
     r"\b(?:dram|nand|hbm|memory chips?|memory manufactur\w*|memory production|memory fabrication|micron|sk hynix)\b"),
    ("electric_vehicles", "Electric vehicles", "Electric-car references and curated vehicle issuers' EV exposure, including diversified manufacturers.",
     r"\b(?:electric vehicles?|electric cars?|ev (?:sales|deliveries|production|manufactur\w*|batteries|charging)|vehicle batter(?:y|ies)|battery electric|charging stations?|automotive electrification)\b"),
)
_PATTERNS = {ident: re.compile(pattern, re.I) for ident, _label, _description, pattern in _TOPICS}
_ORDER = list(HIERARCHY)


def _text(value):
    return str(value or "")[:24000]


def matches(text):
    """Return each literal matched phrase, bounded and deterministic."""
    value = _text(text)
    return {ident: sorted({match.group(0).lower() for match in pattern.finditer(value)})[:12]
            for ident, pattern in _PATTERNS.items() if pattern.search(value)}


def _ordered(values):
    return expand_topics(values)


def case_key(case):
    """The display dedupe identity, not a prospective quality episode."""
    source = case.get("input_id") or case.get("source_input_id")
    if source is not None:
        source = "input:" + str(source)
    elif case.get("run_id"):
        source = "run:" + str(case["run_id"])
    else:
        source = "case:" + str(case.get("id"))
    return source, str(case.get("ticker") or "").upper()


def _case_text(case):
    # Never scan a raw prompt, response, account snapshot, outcome or replay.
    # Only supplied displayed observations are used. A later return does not
    # retroactively supply the earlier event's theme.
    parts = [_text(case.get("reason")), _text(case.get("signals"))]
    features = case.get("features")
    if isinstance(features, dict):
        for key in ("setup", "sector", "industry", "theme", "catalyst", "event"):
            if isinstance(features.get(key), str):
                parts.append(_text(features[key]))
    return "\n".join(parts)


def _outcome(case, horizon=3):
    outcomes = case.get("outcomes") or case.get("paper_outcomes") or {}
    if isinstance(outcomes, dict):
        return outcomes.get(str(horizon)) or outcomes.get(horizon) or {}
    if isinstance(outcomes, list):
        return next((o for o in outcomes if isinstance(o, dict) and o.get("horizon") == horizon), {})
    return {}


def annotate(landmarks, case_groups, *, config_hash=None, observations=None, observation_counts=None):
    """Annotate presentation copies in place; return catalog and method metadata.

    Case groups are the already-scoped bounded prospective display rows and
    historical citation audit. An older generic rule acquires a topic association
    only from cases that explicitly cite its ID *and* its exact policy version.
    This is a labeled association, never a rewrite of the rule or proof of effect.
    """
    all_cases = []
    unique = {}
    for group in case_groups:
        for case in group:
            if not isinstance(case, dict):
                continue
            if config_hash is not None and case.get("config_hash") not in (None, config_hash):
                continue
            found = matches(_case_text(case))
            ticker = str(case.get("ticker") or "").upper()
            references = set(ISSUER_THEMES.get(ticker, ()))
            case["market_themes"] = _ordered(found.keys() | references) or ["general"]
            case["theme_evidence"] = [{"theme_id": theme, "source": "case_context", "matches": words}
                                      for theme, words in found.items()]
            case["theme_evidence"].extend(
                {"theme_id": theme, "source": "ticker_reference", "matches": [ticker],
                 "reference_id": ISSUER_REFERENCE_ID,
                 "note": "Curated issuer/industry exposure; not evidence of this cycle's catalyst or event."}
                for theme in _ordered(references))
            all_cases.append(case)
            key = case_key(case)
            unique.setdefault(key, case)

    # The same saved input/ticker may appear in the prospective ledger and the
    # historical citation audit. Unite annotations only, never actions/outcomes,
    # so choosing the richer audit view cannot double the displayed case count.
    grouped = defaultdict(list)
    for case in all_cases:
        grouped[case_key(case)].append(case)
    for cases in grouped.values():
        topics = _ordered(theme for case in cases for theme in case["market_themes"] if theme != "general") or ["general"]
        evidence = {}
        for case in cases:
            for entry in case["theme_evidence"]:
                key = (entry["theme_id"], entry["source"], tuple(entry.get("matches") or ()))
                evidence.setdefault(key, entry)
        for case in cases:
            case["market_themes"] = list(topics)
            case["theme_evidence"] = list(evidence.values())

    # Prefer the prospective row as the same input/ticker's display observation,
    # while retaining explicit context/citation associations from either source.
    by_citation = defaultdict(list)
    for case in all_cases:
        if isinstance(case.get("prompt_version"), bool):
            continue
        try:
            version = int(case.get("prompt_version"))
        except (TypeError, ValueError):
            continue
        cites = case.get("cited") or case.get("citations") or []
        if not isinstance(cites, list):
            continue
        for cite in cites:
            ident = cite if isinstance(cite, str) else None
            if isinstance(cite, dict):
                ident = cite.get("node_id") or cite.get("id")
            if ident:
                by_citation[(version, ident)].append(case)

    for landmark in landmarks:
        # IDs, parents and field labels must not create market matches. A memory
        # container named MEMORY must not become memory-chip manufacturing.
        found = matches(_text(landmark.get("body")))
        direct = set(found)
        linked = defaultdict(dict)
        versions = landmark.get("versions") or []
        for version in versions:
            try:
                version = int(version)
            except (TypeError, ValueError):
                continue
            for case in by_citation.get((version, landmark.get("id")), []):
                for theme in case["market_themes"]:
                    if theme != "general":
                        linked[theme][case_key(case)] = case
        evidence = [{"theme_id": theme, "source": "direct_text", "matches": words}
                    for theme, words in found.items()]
        evidence.extend({"theme_id": theme, "source": "cited_case", "case_count": len(cases),
                         "case_ids": [str(case.get("id")) for _key, case in sorted(cases.items())][:40]}
                        for theme, cases in linked.items())
        landmark["direct_market_themes"] = _ordered(direct)
        landmark["linked_market_themes"] = _ordered(linked)
        landmark["market_themes"] = _ordered(direct | linked.keys()) or ["general"]
        landmark["theme_evidence"] = evidence

    # Saved news reports and feedback hypotheses are a distinct evidence layer.
    # General news never creates a citation link or edits a policy landmark.
    observed = {}
    for record in observations or ():
        if not isinstance(record, dict) or record.get("source_kind") not in ("news_observation", "feedback_hypothesis"):
            continue
        if config_hash is not None and record.get("config_hash") not in (None, config_hash):
            continue
        ident = record.get("record_id")
        if not isinstance(ident, str) or not re.fullmatch(r"(?:summary|feedback):[0-9]{1,20}", ident):
            continue
        found = matches(_text(record.get("text")))
        record["market_themes"] = _ordered(found) or ["general"]
        record["theme_evidence"] = [{"theme_id": theme, "source": "recorded_observation_text", "matches": words}
                                    for theme, words in found.items()]
        observed.setdefault(ident, record)
    catalog = []
    for ident, topic in HIERARCHY.items():
        cases = [case for case in unique.values() if ident in case["market_themes"]]
        sampled = [record for record in observed.values() if ident in record["market_themes"]]
        counted = (observation_counts or {}).get(ident) or {}
        assessed = [case for case in cases if str(case.get("action") or "").upper()
                    in ("BUY", "PASS", "REJECT", "REJECTED", "SKIP", "NO BUY", "NO_BUY")]
        catalog.append({"id": ident, "label": topic["label"], "description": topic["description"], **topic_metadata(ident),
                        "landmark_count": sum(ident in landmark["market_themes"] for landmark in landmarks),
                        "direct_landmark_count": sum(ident in landmark["direct_market_themes"] for landmark in landmarks),
                        "linked_landmark_count": sum(ident in landmark["linked_market_themes"] for landmark in landmarks),
                        "case_count": len(cases), "assessed_count": len(assessed),
                        "matured_count": sum(_outcome(case).get("status") == "matured" for case in assessed),
                        "observation_count": counted.get("total", len(sampled)),
                        "news_observation_count": counted.get("news_observations", sum(record["source_kind"] == "news_observation" for record in sampled)),
                        "feedback_hypothesis_count": counted.get("feedback_hypotheses", sum(record["source_kind"] == "feedback_hypothesis" for record in sampled)),
                        "sample_observation_count": len(sampled)})
    method = {"id": METHOD_ID, "kind": "deterministic_text_annotations", "multi_label": True,
              "counts_scope": "Bounded displayed cases, deduplicated by input/run and ticker; not quality-rate denominators.",
              "maturity_horizon": 3, "issuer_reference_id": ISSUER_REFERENCE_ID, "taxonomy_version": VERSION,
              "note": "Market themes use recorded words and a small versioned issuer-exposure reference, labeled separately. Issuer exposure does not establish a current event; Iran/conflict needs explicit words. Cited-case links require the same policy version and are associations, not causal credit. Theme grouping does not refit the frozen embedding coordinates or reveal the Decider's decision boundary. Empty themes stay empty; general policy remains unclassified."}
    return catalog, method
