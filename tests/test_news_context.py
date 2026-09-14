"""shared.news_context: which headline triggered a decision, or where the candidate came from."""
from shared import news_context as NC

SUMMARIES = [
    {"agent": "Agent_CNBC", "headlines": ["[CELH] Celsius Holdings — fresh_unconfirmed; Rockstar founder builds a stake",
                                          "[NONE] No tradable company shown — no_catalyst"],
     "insights": "Celsius drew activist interest. Chipotle pulls jalapeños from some restaurants after a salmonella probe. Nothing else."},
    {"agent": "Agent_Fox_Business", "headlines": ["Tesla shares slip as Musk teases robotaxi timeline"], "insights": ""},
]
ENTITIES = [{"symbol": "CMG", "company": "Chipotle Mexican Grill"}, {"symbol": "TSLA", "company": "Tesla"}]


def test_headline_bracket_and_word_matches():
    s = NC.find_snippets("CELH", SUMMARIES)
    assert s and s[0]["agent"] == "Agent_CNBC" and s[0]["text"].startswith("[CELH] Celsius")
    t = NC.find_snippets("TSLA", SUMMARIES, company="Tesla")
    assert t and "robotaxi" in t[0]["text"]


def test_company_name_sentence_from_insights():
    s = NC.find_snippets("CMG", SUMMARIES, company="Chipotle Mexican Grill")
    assert len(s) == 1 and "salmonella" in s[0]["text"] and s[0]["agent"] == "Agent_CNBC"


def test_no_false_positive_on_substrings():
    # "CELH" must not match "CELSIUS"; a 3-letter ticker must not match inside other words
    assert NC.find_snippets("CEL", SUMMARIES) == []
    assert NC.find_snippets("NON", SUMMARIES) == []


def test_attach_sets_context_and_source():
    ds = [
        {"action": "buy", "ticker": "CMG", "reason": "technical pullback"},
        {"action": "sell", "ticker": "TEAM", "reason": "harvest"},
        {"action": "buy", "ticker": "XYZ", "reason": "?"},
        {"action": "hold", "ticker": "CASH", "reason": "cash", "execution_status": "cash_hold"},
        {"kind": "considered_audit", "considered": []},
    ]
    hit = NC.attach_news_context(ds, SUMMARIES, company_entities=ENTITIES,
                                 contrarian=[{"ticker": "XYZ", "setup": "pullback-in-uptrend"}],
                                 holdings=["TEAM"])
    assert hit == 1
    assert ds[0]["news_context"]["source"] == "summarizer news" and ds[0]["news_context"]["snippets"]
    assert ds[1]["news_context"] == {"snippets": [], "source": "existing holding"}
    assert ds[2]["news_context"]["source"] == "contrarian screen (pullback-in-uptrend)"
    assert "news_context" not in ds[3] and "news_context" not in ds[4]


def test_snippets_are_clipped():
    long = [{"agent": "A", "headlines": ["[AAA] " + "x" * 400], "insights": ""}]
    s = NC.find_snippets("AAA", long)
    assert len(s[0]["text"]) <= NC.MAX_SNIPPET_CHARS and s[0]["text"].endswith("…")
