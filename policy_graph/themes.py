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


METHOD_ID = "market_themes_v1"
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
    ("geopolitics_iran", "Iran / geopolitics", "Explicit Iran, conflict or geopolitical references.",
     r"\b(?:iran(?:ian)?|strait of hormuz|hormuz|middle east|geopolitic\w*|armed conflict|ceasefire|military strike\w*)\b|(?<!price )(?<!bidding )\bwar\b"),
    ("energy_oil", "Oil / energy", "Oil, gas, fuel and energy-market references.",
     r"\b(?:oil|crude|brent|wti|opec\+?|natural gas|petroleum|refiner\w*|energy|fuel|lng)\b"),
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
_ORDER = [topic[0] for topic in _TOPICS] + ["general"]


def _text(value):
    return str(value or "")[:24000]


def matches(text):
    """Return each literal matched phrase, bounded and deterministic."""
    value = _text(text)
    return {ident: sorted({match.group(0).lower() for match in pattern.finditer(value)})[:12]
            for ident, pattern in _PATTERNS.items() if pattern.search(value)}


def _ordered(values):
    selected = set(values)
    return [ident for ident in _ORDER if ident in selected]


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


def annotate(landmarks, case_groups, *, config_hash=None):
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

    catalog = []
    topics = [(ident, label, description) for ident, label, description, _ in _TOPICS]
    topics.append(("general", "General policy / unclassified", "No market-topic words are recorded; general policy is not assigned an invented market event."))
    for ident, label, description in topics:
        cases = [case for case in unique.values() if ident in case["market_themes"]]
        assessed = [case for case in cases if str(case.get("action") or "").upper()
                    in ("BUY", "PASS", "REJECT", "REJECTED", "SKIP", "NO BUY", "NO_BUY")]
        catalog.append({"id": ident, "label": label, "description": description,
                        "landmark_count": sum(ident in landmark["market_themes"] for landmark in landmarks),
                        "direct_landmark_count": sum(ident in landmark["direct_market_themes"] for landmark in landmarks),
                        "linked_landmark_count": sum(ident in landmark["linked_market_themes"] for landmark in landmarks),
                        "case_count": len(cases), "assessed_count": len(assessed),
                        "matured_count": sum(_outcome(case).get("status") == "matured" for case in assessed)})
    method = {"id": METHOD_ID, "kind": "deterministic_text_annotations", "multi_label": True,
              "counts_scope": "Bounded displayed cases, deduplicated by input/run and ticker; not quality-rate denominators.",
              "maturity_horizon": 3, "issuer_reference_id": ISSUER_REFERENCE_ID,
              "note": "Market themes use recorded words and a small versioned issuer-exposure reference, labeled separately. Issuer exposure does not establish a current event; Iran/conflict needs explicit words. Cited-case links require the same policy version and are associations, not causal credit. Theme grouping does not refit the frozen embedding coordinates or reveal the Decider's decision boundary. Empty themes stay empty; general policy remains unclassified."}
    return catalog, method
