"""Contrarian context preserves opportunity and protective-stop direction."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import contrarian_screener as screener
from contrarian_screener import format_contrarian_watchlist, format_index_regime


def test_risk_off_keeps_selective_entries_and_every_existing_regime_limit():
    text = format_index_regime({'label':'RISK-OFF','why':'QQQ below 20d MA'})
    assert 'cash is the correct default' not in text
    assert 'RISK-OFF: evaluate selective opportunities' in text
    assert 'up to 3 new BUYs' in text
    assert '5-8% at half size' in text
    assert 'MIXED: at most 2 new BUYs at half size, extension ≤5% only' in text
    assert 'at most 1 new BUY at half size' in text
    assert 'oversold reversal or a name ≤3% above its 20d MA' in text
    assert 'harvest at +2%' in text
    assert 'no re-entry exceptions' in text
    assert 'Hold cash when independent candidate gates fail; never force a BUY' in text


@pytest.mark.parametrize('ma', [104.0,98.0])
def test_ma_above_entry_or_too_distant_below_entry_does_not_become_an_automatic_stop(ma):
    candidate={'ticker':'ABC','setup':'oversold-reversal','price':100.0,'sma20':ma,
               'kill_3pct':97.0,'day':.5,'week':-2.0,'month':-5.0,'rsi':34.0,
               'pullback_from_20d_high':8.0,'dist_from_20d_ma':(100/ma-1)*100}
    before=deepcopy(candidate)
    text=format_contrarian_watchlist([candidate],quarantined=['EXITED'])
    assert candidate == before
    assert f'$100.00 | 20d MA ${ma:.2f} | 3% reference $97.00' in text
    assert 'HIGHER of' not in text and '3% kill' not in text
    assert '20d MA ABOVE entry is a reclaim/resistance level, not a protective stop' in text
    assert 'genuinely evidenced support/invalidation price BELOW entry' in text
    assert 'positive D = (entry - K) / entry × 100' in text
    assert 'Without a justified below-entry K inside that cap, WATCH/PASS' in text
    assert '3% reference is not permission or an exception to the active cap' in text
    assert 'Never invent a tighter stop merely to pass the gate' in text
    assert 'NO re-entry this cycle, whatever the setup): EXITED' in text


def test_empty_candidate_set_does_not_invent_an_opportunity():
    assert format_contrarian_watchlist([]) == ''
    text=format_contrarian_watchlist([],quarantined=['EXITED'])
    assert not any(line.startswith('- ') for line in text.splitlines())
    assert 'EXITED' in text and 'do not force a BUY' in text


def test_red_session_reclaim_surfaces_with_fresh_benchmarks_and_drops_stale_evidence(monkeypatch):
    clock = datetime(2026, 11, 6, 11, tzinfo=ZoneInfo("America/New_York")).timestamp()
    dates = pd.bdate_range(end="2026-11-06", periods=26)
    closes = [118 - 0.75 * i for i in range(25)]

    def bars(opening, low, high, price):
        return pd.DataFrame({"Open": closes + [opening], "Low": closes + [low],
                             "High": closes + [high], "Close": closes + [price]}, index=dates)

    rebound = bars(98, 97.4, 99.1, 98.4)
    declining = bars(98, 97.4, 99.1, 97.8)
    history = pd.concat({"DIP": rebound, "FALL": declining,
                         "SPY": declining, "QQQ": rebound, "SMH": rebound}, axis=1)
    calls = []

    def download(symbols, **kwargs):
        calls.append(symbols)
        if len(calls) > 1:
            raise RuntimeError("synthetic outage")
        return history

    monkeypatch.setenv("DAI_CONTRARIAN_UNIVERSE", "DIP,FALL")
    monkeypatch.setenv("DAI_CONTRARIAN_ENABLED", "1")
    monkeypatch.setenv("DAI_CONTRARIAN_CACHE_MIN", "1")
    monkeypatch.setattr(screener, "_CACHE", {"ts": 0.0, "data": [], "regime": None})
    monkeypatch.setattr(screener.time, "time", lambda: clock)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))

    candidates, regime = screener.get_contrarian_candidates(include_regime=True)
    assert len(calls) == 1
    assert regime["label"] == "RISK-OFF"
    assert "SMH -1.60% vs prior close, +1.03% off low, open reclaimed" in format_index_regime(regime)
    assert [c["ticker"] for c in candidates] == ["DIP"]
    assert candidates[0]["day"] < 0
    assert candidates[0]["session_low"] == 97.4
    assert screener.get_contrarian_candidates(exclude={"DIP"}) == []
    assert len(calls) == 1

    clock += 120
    stale, unavailable = screener.get_contrarian_candidates(include_regime=True)
    assert unavailable is None
    assert stale[0]["snapshot_stale"]
    assert "session_low" not in stale[0]
    assert "STALE SCREEN SNAPSHOT" in format_contrarian_watchlist(stale)
