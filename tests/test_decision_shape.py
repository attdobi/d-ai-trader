"""Canonical decision JSON schema for decider output.

Expected shape per decision object:
- action: str in {"buy", "sell", "hold"}
- ticker: non-empty str
- amount_usd: int | float (non-negative)
- reason: non-empty str
"""

from typing import Any, Dict, Tuple


REQUIRED_KEYS = {"action", "ticker", "amount_usd", "reason"}
VALID_ACTIONS = {"buy", "sell", "hold"}


def validate_decision_shape(decision: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(decision, dict):
        return False, "decision must be a dict"

    missing = REQUIRED_KEYS - set(decision.keys())
    if missing:
        return False, f"missing required fields: {sorted(missing)}"

    action = decision["action"]
    ticker = decision["ticker"]
    amount_usd = decision["amount_usd"]
    reason = decision["reason"]

    if not isinstance(action, str) or action.lower() not in VALID_ACTIONS:
        return False, f"invalid action: {action!r}"

    if not isinstance(ticker, str) or not ticker.strip():
        return False, "ticker must be a non-empty string"

    if not isinstance(amount_usd, (int, float)):
        return False, "amount_usd must be numeric"

    if amount_usd < 0:
        return False, "amount_usd must be non-negative"

    if not isinstance(reason, str) or not reason.strip():
        return False, "reason must be a non-empty string"

    return True, ""


def test_valid_buy_decision_matches_schema() -> None:
    decision = {"action": "buy", "ticker": "NVDA", "amount_usd": 1500.0, "reason": "Breakout momentum"}
    ok, error = validate_decision_shape(decision)
    assert ok, f"Expected BUY decision schema to be valid, got error: {error}"


def test_valid_sell_decision_matches_schema() -> None:
    decision = {"action": "sell", "ticker": "AAPL", "amount_usd": 1200, "reason": "Risk reduction"}
    ok, error = validate_decision_shape(decision)
    assert ok, f"Expected SELL decision schema to be valid, got error: {error}"


def test_valid_hold_decision_matches_schema() -> None:
    decision = {"action": "hold", "ticker": "MSFT", "amount_usd": 0, "reason": "Maintain position"}
    ok, error = validate_decision_shape(decision)
    assert ok, f"Expected HOLD decision schema to be valid, got error: {error}"


def test_missing_field_is_rejected() -> None:
    decision = {"action": "buy", "ticker": "TSLA", "amount_usd": 2000}
    ok, error = validate_decision_shape(decision)
    assert not ok, "Expected schema validation to reject decision missing required fields"
    assert "missing required fields" in error, "Expected missing-field error message for schema guardrail"


def test_invalid_action_is_rejected() -> None:
    decision = {"action": "accumulate", "ticker": "GOOG", "amount_usd": 1800, "reason": "Strong signal"}
    ok, error = validate_decision_shape(decision)
    assert not ok, "Expected schema validation to reject unsupported action values"
    assert "invalid action" in error, "Expected invalid-action error message for schema guardrail"
