"""Contrarian context preserves opportunity and protective-stop direction."""
from copy import deepcopy

import pytest

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
