"""Which summarizer headline (if any) triggered a decision — attached to every decision so
the Trades tab can show the news snippet, or say plainly that there was none and where
the candidate came from instead (contrarian screen, existing holding, …).

Pure functions: no DB, no network. The trader calls attach_news_context() once per cycle.
"""
from __future__ import annotations

import re

MAX_SNIPPETS = 2
MAX_SNIPPET_CHARS = 220

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _company_names(company_entities) -> dict:
    """{TICKER: company name} from the CompanyExtractionAgent entities."""
    names = {}
    for e in company_entities or []:
        if not isinstance(e, dict):
            continue
        sym = str(e.get("symbol") or "").strip().upper()
        name = str(e.get("company") or "").strip()
        if sym and name and len(name) >= 3:
            names[sym] = name
    return names


def _mentions(text: str, ticker: str, company: str | None) -> bool:
    if not text:
        return False
    if f"[{ticker}]" in text:
        return True
    if re.search(rf"(?<![A-Z]){re.escape(ticker)}(?![A-Z])", text):
        return True
    if company:
        # first significant word of the company name ("Chipotle" for "Chipotle Mexican Grill")
        head = re.split(r"[\s,]+", company)[0]
        if len(head) >= 4 and head.lower() not in ("the", "inc", "corp", "group", "holdings"):
            if re.search(rf"\b{re.escape(head)}\b", text, re.I):
                return True
    return False


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_SNIPPET_CHARS else text[:MAX_SNIPPET_CHARS - 1].rstrip() + "…"


def find_snippets(ticker: str, parsed_summaries, company: str | None = None) -> list:
    """[{agent, text}] — headlines first, then the insight sentence that mentions the ticker."""
    ticker = (ticker or "").upper()
    out = []
    for s in parsed_summaries or []:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent") or "unknown")
        for h in s.get("headlines") or []:
            if _mentions(str(h), ticker, company):
                out.append({"agent": agent, "text": _clip(h)})
                if len(out) >= MAX_SNIPPETS:
                    return out
    for s in parsed_summaries or []:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent") or "unknown")
        for sent in _SENTENCE_SPLIT.split(str(s.get("insights") or "")):
            if _mentions(sent, ticker, company):
                out.append({"agent": agent, "text": _clip(sent)})
                if len(out) >= MAX_SNIPPETS:
                    return out
    return out


def candidate_source(ticker: str, *, contrarian=None, holdings=(), company_entities=None) -> str:
    """Where a ticker with no news mention came from."""
    ticker = (ticker or "").upper()
    for c in contrarian or []:
        if isinstance(c, dict) and str(c.get("ticker") or "").upper() == ticker:
            return f"contrarian screen ({c.get('setup') or 'technical setup'})"
    if ticker in {str(h).upper() for h in holdings or []}:
        return "existing holding"
    if ticker in _company_names(company_entities):
        return "news entity (mentioned, but no headline matched)"
    return "not in this cycle's news, screen, or holdings"


def attach_news_context(decisions, parsed_summaries, *, company_entities=None, contrarian=None,
                        holdings=()) -> int:
    """Set decision['news_context'] = {snippets: [...], source: str} on every ticker decision
    (in place). Returns how many decisions got at least one news snippet."""
    names = _company_names(company_entities)
    hit = 0
    for d in decisions or []:
        if not isinstance(d, dict) or d.get("kind"):
            continue
        ticker = str(d.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        snippets = find_snippets(ticker, parsed_summaries, names.get(ticker))
        if snippets:
            hit += 1
            d["news_context"] = {"snippets": snippets, "source": "summarizer news"}
        else:
            d["news_context"] = {"snippets": [], "source": candidate_source(
                ticker, contrarian=contrarian, holdings=holdings, company_entities=company_entities)}
    return hit
