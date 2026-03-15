import decision_validator as dv_module


def _invalid_errors(invalid):
    return [item["validation_error"] for item in invalid]


def _set_amount_limits_for_deterministic_tests():
    dv_module.MIN_BUY_AMOUNT = 1000.0
    dv_module.MAX_BUY_AMOUNT = 4000.0


def test_sell_nonexistent_ticker_is_rejected():
    _set_amount_limits_for_deterministic_tests()

    validator = dv_module.DecisionValidator(
        current_holdings=[{"ticker": "AAPL", "shares": 5, "current_price": 200.0}],
        available_cash=5000.0,
    )

    valid, invalid = validator.validate_decisions(
        [{"action": "sell", "ticker": "TSLA", "amount_usd": 1500.0, "reason": "Take profit"}]
    )

    assert not valid, "Expected no valid decisions when selling a ticker that is not held"
    assert invalid, "Expected sell-nonexistent-ticker decision to be rejected"
    assert "Cannot sell TSLA" in _invalid_errors(invalid)[0], "Guardrail must block hallucinated SELL decisions"


def test_buy_already_held_ticker_is_rejected():
    _set_amount_limits_for_deterministic_tests()

    validator = dv_module.DecisionValidator(
        current_holdings=[{"ticker": "AAPL", "shares": 3, "current_price": 180.0}],
        available_cash=5000.0,
    )

    valid, invalid = validator.validate_decisions(
        [{"action": "buy", "ticker": "AAPL", "amount_usd": 1200.0, "reason": "Re-enter"}]
    )

    assert not valid, "Expected no valid decisions when buying a ticker that is already held"
    assert invalid, "Expected buy-duplicate-ticker decision to be rejected"
    assert "already own" in _invalid_errors(invalid)[0], "Guardrail must reject BUY for already-held tickers"


def test_buy_amount_zero_is_rejected():
    _set_amount_limits_for_deterministic_tests()

    validator = dv_module.DecisionValidator(current_holdings=[], available_cash=5000.0)

    valid, invalid = validator.validate_decisions(
        [{"action": "buy", "ticker": "NVDA", "amount_usd": 0, "reason": "Test guardrail"}]
    )

    assert not valid, "Expected no valid decisions when buy amount is zero"
    assert invalid, "Expected zero-amount BUY decision to be rejected"
    error = _invalid_errors(invalid)[0]
    assert (
        "too small" in error.lower() or "minimum" in error.lower()
    ), "Guardrail must reject BUY decisions with zero amount"


def test_buy_amount_exceeding_cash_is_rejected():
    _set_amount_limits_for_deterministic_tests()

    validator = dv_module.DecisionValidator(current_holdings=[], available_cash=1500.0)

    valid, invalid = validator.validate_decisions(
        [{"action": "buy", "ticker": "AMZN", "amount_usd": 2000.0, "reason": "Momentum entry"}]
    )

    assert not valid, "Expected no valid decisions when buy amount exceeds cash"
    assert invalid, "Expected over-cash BUY decision to be rejected"
    assert "exceeds available cash" in _invalid_errors(invalid)[0], "Guardrail must cap BUY amount at available cash"


def test_allow_sell_reuse_false_keeps_cash_unchanged_after_sell():
    _set_amount_limits_for_deterministic_tests()

    starting_cash = 1000.0
    validator = dv_module.DecisionValidator(
        current_holdings=[{"ticker": "AAPL", "shares": 10, "current_price": 150.0, "current_value": 1500.0}],
        available_cash=starting_cash,
        allow_sell_reuse=False,
    )

    decisions = [
        {"action": "sell", "ticker": "AAPL", "amount_usd": 1500.0, "reason": "Exit position"},
        {"action": "buy", "ticker": "TSLA", "amount_usd": 2000.0, "reason": "New setup"},
    ]

    valid, invalid = validator.validate_decisions(decisions)

    assert len(valid) == 1 and valid[0]["action"] == "sell", (
        "Expected SELL to validate first while subsequent BUY fails when sell proceeds are not reusable"
    )
    assert validator.available_cash == starting_cash, "Cash must remain unchanged when allow_sell_reuse=False"
    assert len(invalid) == 1 and invalid[0]["decision"]["action"] == "buy", (
        "Expected BUY to be rejected after SELL when unsettled proceeds cannot be reused"
    )
    assert "exceeds available cash" in invalid[0]["validation_error"], (
        "BUY rejection should explicitly state that amount exceeds available cash"
    )


def test_rank_prefixed_ticker_is_normalized_for_validation():
    _set_amount_limits_for_deterministic_tests()

    validator = dv_module.DecisionValidator(
        current_holdings=[{"ticker": "TSLA", "shares": 2, "current_price": 180.0}],
        available_cash=5000.0,
    )

    decisions = [{"action": "sell", "ticker": "r2/tsla", "amount_usd": 500.0, "reason": "Trim"}]
    valid, invalid = validator.validate_decisions(decisions)

    assert not invalid, "Rank-prefixed ticker should normalize and pass holdings check"
    assert valid[0]["ticker"] == "TSLA", "Validated decision should store canonical uppercase ticker"
