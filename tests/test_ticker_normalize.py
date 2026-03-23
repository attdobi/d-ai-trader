"""Safety-net tests for shared ticker normalization."""

from __future__ import annotations

import pytest

from shared.ticker_normalize import normalize_ticker


def test_normalize_ticker_keeps_plain_uppercase_symbol():
    assert normalize_ticker("TSLA") == "TSLA"


def test_normalize_ticker_upcases_lowercase_symbol():
    assert normalize_ticker("tsla") == "TSLA"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("R1-TSLA", "TSLA"), ("r2/TSLA", "TSLA")],
)
def test_normalize_ticker_strips_rank_prefixes(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_normalize_ticker_empty_inputs_return_empty_string(raw):
    assert normalize_ticker(raw) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("R1-", "R1-"), ("r2/", "R2/")],
)
def test_normalize_ticker_malformed_rank_prefix_is_preserved(raw, expected):
    """Current behavior: malformed rank prefixes are normalized but not stripped."""
    assert normalize_ticker(raw) == expected
